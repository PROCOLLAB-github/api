"""Общие определения формы и проверки значений без изменения старого Project."""

import hashlib
import json
import math
from urllib.parse import urlsplit

from partner_programs.solution_errors import SolutionError, issue

FIELD_TYPES = ("text", "textarea", "url", "number", "select", "checkbox", "file", "radio")
PURPOSES = (
    "other",
    "case",
    "presentation",
    "repository",
    "demo",
    "video",
    "run_instructions",
)
TEMPLATES = ("case_championship", "hackathon")
MAX_FILE_SIZE = 104857600
VALIDATION_DEFAULTS = dict(
    min_length=None,
    max_length=None,
    minimum=None,
    maximum=None,
    allowed_extensions=[],
    max_file_size_bytes=None,
)


def empty_value(value):
    return value is None or isinstance(value, str) and not value.strip()


def field_data(field):
    validation = field.validation if isinstance(field.validation, dict) else {}
    return dict(
        id=field.pk,
        type=field.field_type,
        purpose="case" if field.name == "case" else field.purpose,
        label=field.label,
        help_text=field.help_text or "",
        required=field.is_required,
        position=field.position,
        options=field.get_options_list(),
        validation={
            k: list(validation.get(k, v))
            if k == "allowed_extensions"
            else validation.get(k, v)
            for k, v in VALIDATION_DEFAULTS.items()
        },
    )


def form_data(program):
    fields = [field_data(field) for field in program.fields.order_by("position", "pk")]
    definition = dict(template=program.solution_template, fields=fields)
    revision = hashlib.sha256(
        json.dumps(
            definition, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    configured = program.solution_template in TEMPLATES and any(
        f["purpose"] == "case"
        and f["type"] == "select"
        and f["required"]
        and f["options"]
        for f in fields
    )
    return dict(
        program_id=program.pk,
        revision=revision,
        template=program.solution_template,
        is_configured=bool(configured),
        is_snapshot=False,
        fields=fields,
    )


def definition_error(path, detail, field_id=None, *, code="invalid", status=400):
    raise SolutionError(
        "validation_error" if status == 400 else code,
        detail,
        status=status,
        errors=[issue(path, code, detail, field_id)],
    )


def validate_definition(field):
    field_id = field.get("id")
    path = f"fields.{field_id}" if field_id else "fields"
    kind, purpose, validation = field["type"], field["purpose"], field["validation"]
    if not field["label"].strip():
        definition_error(path + ".label", "Укажите подпись поля.", field_id)
    required_types = dict(
        case="select",
        presentation="file",
        repository="url",
        demo="url",
        video="url",
        run_instructions="textarea",
    )
    if purpose in required_types and kind != required_types[purpose]:
        definition_error(
            path + ".type", "Тип не соответствует назначению поля.", field_id
        )
    if purpose == "case" and not field["required"]:
        definition_error(
            path + ".required", "Выбор кейса или задачи обязателен.", field_id
        )
    options = field["options"]
    if kind in ("select", "radio"):
        if not options or any(not value.strip() for value in options):
            definition_error(
                path + ".options", "Добавьте непустые варианты выбора.", field_id
            )
        if len({value.strip().casefold() for value in options}) != len(options):
            definition_error(
                path + ".options", "Варианты не должны повторяться.", field_id
            )
    elif options:
        definition_error(
            path + ".options", "Варианты доступны только полям выбора.", field_id
        )
    for lower, upper in (("min_length", "max_length"), ("minimum", "maximum")):
        if validation[lower] is not None and validation[upper] is not None:
            if validation[lower] > validation[upper]:
                definition_error(
                    path + ".validation", "Минимум превышает максимум.", field_id
                )
    if kind not in ("text", "textarea", "url"):
        if any(validation[k] is not None for k in ("min_length", "max_length")):
            definition_error(
                path + ".validation", "Длина задается для текстового поля.", field_id
            )
    if kind != "number" and any(
        validation[k] is not None for k in ("minimum", "maximum")
    ):
        definition_error(path + ".validation", "Диапазон задается для числа.", field_id)
    if kind != "file" and (
        validation["allowed_extensions"] or validation["max_file_size_bytes"]
    ):
        definition_error(
            path + ".validation", "Размер и расширения задаются для файла.", field_id
        )
    extensions = validation["allowed_extensions"]
    if len(set(extensions)) != len(extensions):
        definition_error(
            path + ".validation", "Расширения не должны повторяться.", field_id
        )


def value_problem(field, value):
    """None означает допустимый непустой ответ; required проверяется отдельно."""
    kind, validation = field["type"], field["validation"]
    if kind in ("text", "textarea", "url", "select", "radio") and not isinstance(
        value, str
    ):
        return "invalid_type", "Ожидается текст."
    if kind in ("select", "radio") and value not in field["options"]:
        return "invalid_choice", "Выберите актуальный вариант."
    if kind == "checkbox" and not isinstance(value, bool):
        return "invalid_type", "Ожидается логическое значение."
    if kind == "number":
        try:
            finite = math.isfinite(value) if isinstance(value, (int, float)) else False
        except OverflowError:
            finite = False
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite:
            return "invalid_type", "Ожидается конечное число."
        if validation["minimum"] is not None and value < validation["minimum"]:
            return "minimum", "Число меньше допустимого."
        if validation["maximum"] is not None and value > validation["maximum"]:
            return "maximum", "Число больше допустимого."
    if kind in ("text", "textarea", "url"):
        if validation["min_length"] is not None and len(value) < validation["min_length"]:
            return "min_length", "Текст короче допустимого."
        if validation["max_length"] is not None and len(value) > validation["max_length"]:
            return "max_length", "Текст длиннее допустимого."
    if kind == "url":
        try:
            url = urlsplit(value)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
            ):
                return "invalid_url", "Укажите ссылку HTTP или HTTPS."
            if any(char.isspace() for char in value):
                return "invalid_url", "Ссылка не должна содержать пробелы."
            url.port
        except ValueError:
            return "invalid_url", "Укажите корректную ссылку."
    if kind == "file":
        if (
            not isinstance(value, dict)
            or set(value) != {"url"}
            or not isinstance(value["url"], str)
        ):
            return "invalid_type", "Укажите один загруженный файл."
    return None


def template_fields():
    def field(kind, purpose, label, required=False, **validation):
        return dict(
            id=None,
            type=kind,
            purpose=purpose,
            label=label,
            help_text="",
            required=required,
            position=0,
            options=[],
            validation={**VALIDATION_DEFAULTS, "allowed_extensions": [], **validation},
        )

    def case(label):
        return field("select", "case", label, True)

    def description():
        return field("textarea", "other", "Краткое описание", True, max_length=3000)

    def presentation(required):
        return field(
            "file",
            "presentation",
            "Презентация PDF",
            required,
            allowed_extensions=["pdf"],
            max_file_size_bytes=20971520,
        )

    def extras():
        return [
            field("url", "video", "Видео"),
            field(
                "file",
                "other",
                "Дополнительные материалы",
                allowed_extensions=["pdf", "zip"],
                max_file_size_bytes=52428800,
            ),
        ]

    rows = [
        dict(
            key="case_championship",
            label="Кейс-чемпионат",
            fields=[case("Кейс"), description(), presentation(True), *extras()],
        ),
        dict(
            key="hackathon",
            label="Хакатон",
            fields=[
                case("Задача или трек"),
                description(),
                field("textarea", "other", "Описание реализации", True, max_length=10000),
                field("url", "repository", "Репозиторий", True),
                field("textarea", "run_instructions", "Инструкция запуска", True),
                field("url", "demo", "Демо"),
                presentation(False),
                *extras(),
            ],
        ),
    ]
    for template in rows:
        for position, row in enumerate(template["fields"]):
            row["position"] = position
    return dict(results=rows, max_file_size_bytes=MAX_FILE_SIZE, files_per_field=1)
