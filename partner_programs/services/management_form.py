"""Atomic organizer editing of program case names and shared project fields."""

import hashlib
import json
from uuid import uuid4

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError

from partner_programs.models import PartnerProgramField, PartnerProgramProject
from partner_programs.serializers.management import StrictFieldsMixin
from partner_programs.services.management import managed_program

SUPPORTED_TYPES = ("text", "textarea", "select", "file")


class StaleProjectForm(APIException):
    status_code = 409
    default_code = "stale_project_form"
    default_detail = "Кейсы или поля изменены другим организатором. Обновите настройки."

    def __init__(self):
        super().__init__({"code": self.default_code, "detail": self.default_detail})


class FormFieldWrite(StrictFieldsMixin, serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    label = serializers.CharField(max_length=256)
    field_type = serializers.ChoiceField(
        choices=[p[0] for p in PartnerProgramField.FIELD_TYPES]
    )
    is_required = serializers.BooleanField()
    help_text = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=4000
    )
    options = serializers.ListField(
        child=serializers.CharField(max_length=1000), max_length=200
    )


class ProjectFormWrite(StrictFieldsMixin, serializers.Serializer):
    expected_updated_at = serializers.DateTimeField()
    expected_revision = serializers.CharField(max_length=64)
    cases = serializers.ListField(
        child=serializers.CharField(max_length=1000), max_length=200
    )
    fields = FormFieldWrite(many=True)

    def validate_fields(self, value):
        if len(value) > 100:
            raise serializers.ValidationError("Допустимо не больше 100 полей.")
        ids = [v["id"] for v in value if v.get("id") is not None]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Поле указано несколько раз.")
        return value


def _options(values):
    if any(not v.strip() or "|" in v for v in values):
        raise ValidationError("Варианты должны быть непустыми и не содержать символ |.")
    if len({v.strip().casefold() for v in values}) != len(values):
        raise ValidationError("Варианты не должны повторяться.")
    return [v.strip() for v in values]


def _definitions(program):
    return list(program.fields.order_by("pk"))


def form_data(program):
    fields = _definitions(program)
    definitions = [
        {
            "id": f.pk,
            "name": f.name,
            "label": f.label,
            "field_type": f.field_type,
            "is_required": f.is_required,
            "help_text": f.help_text or "",
            "options": f.get_options_list(),
            "show_filter": f.show_filter,
        }
        for f in fields
    ]
    revision = hashlib.sha256(
        json.dumps(definitions, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    counts = dict(
        program.fields.annotate(
            total=Count("values", filter=Q(values__value_text__regex=r"\S"))
        ).values_list("pk", "total")
    )
    case = next((f for f in fields if f.name == "case"), None)
    case_counts = (
        dict(
            case.values.values("value_text")
            .annotate(total=Count("program_project", distinct=True))
            .values_list("value_text", "total")
        )
        if case
        else {}
    )
    return {
        "updated_at": program.datetime_updated,
        "revision": revision,
        "has_projects": PartnerProgramProject.objects.filter(
            partner_program=program
        ).exists(),
        "cases": [
            {"name": option, "projects_count": case_counts.get(option, 0)}
            for option in (case.get_options_list() if case else [])
        ],
        "fields": [
            {
                **data,
                "answers_count": counts.get(data["id"], 0),
                "editable_type": data["field_type"] in SUPPORTED_TYPES,
            }
            for data in definitions
            if data["name"] != "case"
        ],
        "supported_types": SUPPORTED_TYPES,
    }


@transaction.atomic
def save_form(program_id, user, payload):
    program = managed_program(program_id, user, lock=True)
    # Same link -> definition order as field PUT/submit; application creation
    # already locks the program, so the first project cannot race configuration.
    list(
        PartnerProgramProject.objects.filter(partner_program=program)
        .order_by("pk")
        .select_for_update()
    )
    existing = list(program.fields.order_by("pk").select_for_update())
    serializer = ProjectFormWrite(data=payload)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    snapshot = form_data(program)
    if (
        data["expected_updated_at"] != program.datetime_updated
        or data["expected_revision"] != snapshot["revision"]
    ):
        raise StaleProjectForm()
    cases = _options(data["cases"])
    generic = {f.pk: f for f in existing if f.name != "case"}
    case = next((f for f in existing if f.name == "case"), None)
    ids = {item["id"] for item in data["fields"] if item.get("id") is not None}
    if ids - generic.keys():
        raise ValidationError({"fields": "Поле не относится к этой программе."})
    for pk, field in generic.items():
        if pk not in ids:
            if field.values.filter(value_text__regex=r"\S").exists():
                raise ValidationError(
                    {"fields": "Нельзя удалить поле с сохраненными ответами."}
                )
            field.delete()
    for item in data["fields"]:
        field = generic.get(item.get("id"))
        new = field is None
        if new and item["field_type"] not in SUPPORTED_TYPES:
            raise ValidationError({"fields": "Этот тип недоступен для новых полей."})
        options = (
            _options(item["options"])
            if item["field_type"] in ("select", "radio")
            else item["options"]
        )
        if item["field_type"] in ("select", "radio") and not options:
            raise ValidationError({"fields": "Укажите варианты ответа."})
        if item["field_type"] not in ("select", "radio", "checkbox") and options:
            raise ValidationError({"fields": "Варианты доступны только полям выбора."})
        if field and field.values.filter(value_text__regex=r"\S").exists():
            if field.field_type != item["field_type"]:
                raise ValidationError({"fields": "Нельзя изменить тип поля с ответами."})
            if field.field_type in ("select", "radio"):
                used = set(
                    field.values.exclude(value_text="").values_list(
                        "value_text", flat=True
                    )
                )
                if used - set(options):
                    raise ValidationError(
                        {
                            "fields": "Нельзя удалить или переименовать использованный вариант ответа."
                        }
                    )
        if field and field.field_type not in SUPPORTED_TYPES:
            if (
                item["field_type"] != field.field_type
                or options != field.get_options_list()
                or item["is_required"] != field.is_required
            ):
                raise ValidationError(
                    {
                        "fields": "Настройки существующего специального поля нужно сохранить."
                    }
                )
        if new:
            field = PartnerProgramField(
                partner_program=program, name="field_" + uuid4().hex
            )
        field.label = item["label"]
        field.field_type = item["field_type"]
        field.is_required = item["is_required"]
        field.help_text = item["help_text"]
        field.options = "|".join(options)
        try:
            field.full_clean()
            field.save()
        except ModelValidationError as error:
            raise ValidationError({"fields": error.messages})
    if case:
        if not cases:
            if case.values.exists():
                raise ValidationError(
                    {"cases": "Нельзя удалить кейсы, которые уже выбрали команды."}
                )
            case.delete()
        else:
            case.options = "|".join(cases)
            try:
                case.save()
            except ModelValidationError as error:
                raise ValidationError({"cases": error.messages})
    elif cases:
        PartnerProgramField.objects.create(
            partner_program=program,
            name="case",
            label="Кейс",
            field_type="select",
            is_required=True,
            show_filter=True,
            options="|".join(cases),
        )
    program.save(update_fields=["datetime_updated"])
    return form_data(program)
