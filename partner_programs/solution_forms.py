"""Атомарное управление формой программы; существующие ответы остаются сохранными."""

import json
from uuid import uuid4

from django.db import transaction

from files.models import UserFile
from partner_programs.models import PartnerProgramField, PartnerProgramUserProfile
from partner_programs.permissions import can_manage_program
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_schema import (
    definition_error,
    empty_value,
    field_data,
    form_data,
    validate_definition,
    value_problem,
)
from partner_programs.solution_team import program_for


def require_manager(program, actor):
    if not can_manage_program(actor, program):
        raise SolutionError(
            "forbidden", "Настройка формы доступна организатору программы.", status=403
        )


def require_reader(program, actor):
    if (
        not can_manage_program(actor, program)
        and not PartnerProgramUserProfile.objects.filter(
            partner_program=program, user=actor
        ).exists()
    ):
        raise SolutionError(
            "forbidden", "Форма доступна участникам этой программы.", status=403
        )


def stored_values(field):
    values = list(field.solution_answers.values_list("value", flat=True))
    for value in field.values.values_list("value_text", flat=True):
        if field.field_type in ("number", "checkbox", "file"):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                if field.field_type == "file":
                    value = {"url": value}
        values.append(value)
    return [value for value in values if not empty_value(value)]


def answer_count(field):
    return len(stored_values(field))


def has_answers(program):
    return any(answer_count(field) for field in program.fields.all())


def restrictions_narrowed(before, after):
    for key in ("min_length", "minimum"):
        if after[key] is not None and (before[key] is None or after[key] > before[key]):
            return True
    for key in ("max_length", "maximum", "max_file_size_bytes"):
        if after[key] is not None and (before[key] is None or after[key] < before[key]):
            return True
    old_extensions, new_extensions = set(before["allowed_extensions"]), set(
        after["allowed_extensions"]
    )
    return bool(
        new_extensions and (not old_extensions or old_extensions - new_extensions)
    )


def check_evolution(field, candidate):
    values = stored_values(field)
    if not values:
        return
    previous = field_data(field)
    path = f"fields.{field.pk}"
    if candidate is None:
        definition_error(
            path,
            "Нельзя удалить поле с ответами.",
            field.pk,
            code="field_in_use",
            status=409,
        )
    if (
        candidate["type"] != previous["type"]
        or candidate["purpose"] != previous["purpose"]
    ):
        definition_error(
            path,
            "Нельзя менять тип или назначение поля с ответами.",
            field.pk,
            code="field_in_use",
            status=409,
        )
    if candidate["type"] in ("select", "radio"):
        if any(value not in candidate["options"] for value in values):
            definition_error(
                path + ".options",
                "Нельзя удалить или переименовать используемый вариант.",
                field.pk,
                code="option_in_use",
                status=409,
            )
    if not restrictions_narrowed(previous["validation"], candidate["validation"]):
        return
    for value in values:
        problem = value_problem(candidate, value)
        if candidate["type"] == "file" and not problem:
            upload = UserFile.objects.filter(pk=value["url"]).first()
            rules = candidate["validation"]
            if upload is None:
                problem = ("file_not_found", "Данные существующего файла недоступны.")
            elif (
                rules["max_file_size_bytes"]
                and upload.size > rules["max_file_size_bytes"]
            ):
                problem = ("file_too_large", "Существующий файл превышает новый предел.")
            elif (
                rules["allowed_extensions"]
                and upload.extension.lower() not in rules["allowed_extensions"]
            ):
                problem = (
                    "file_type_not_allowed",
                    "Существующий тип файла исключен новым правилом.",
                )
        if problem:
            definition_error(
                path + ".validation",
                "Новому ограничению не соответствуют сохраненные ответы.",
                field.pk,
                code="constraint_in_use",
                status=409,
            )


def management_data(program):
    form = form_data(program)
    fields = list(program.fields.all())
    usage = [
        dict(field_id=field.pk, answers_count=answer_count(field)) for field in fields
    ]
    for row in usage:
        row.update(
            can_delete=row["answers_count"] == 0,
            can_change_type=row["answers_count"] == 0,
        )
    required = {field["id"] for field in form["fields"] if field["required"]}
    affected = 0
    for solution in program.solutions.filter(status="draft").prefetch_related("answers"):
        present = {
            row.field_id for row in solution.answers.all() if not empty_value(row.value)
        }
        if required - present:
            affected += 1
    return dict(
        form=form,
        has_solutions=program.solutions.exists(),
        has_answers=any(row["answers_count"] for row in usage),
        affected_draft_count=affected,
        fields_usage=sorted(usage, key=lambda row: row["field_id"]),
    )


@transaction.atomic
def save_form(*, program_id, actor, expected_revision, template, fields):
    program = program_for(program_id, lock=True)
    require_manager(program, actor)
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует проектную форму."
        )
    if form_data(program)["revision"] != expected_revision:
        raise SolutionError(
            "form_revision_conflict",
            "Форма изменена другим организатором.",
            meta={"current_form_revision": form_data(program)["revision"]},
        )
    existing = {row.pk: row for row in program.fields.select_for_update().order_by("pk")}
    used = any(answer_count(row) for row in existing.values())
    if program.solution_template != template and used:
        raise SolutionError(
            "template_in_use", "После появления ответов шаблон нельзя менять."
        )
    ids = [row["id"] for row in fields if row["id"] is not None]
    if len(ids) != len(set(ids)) or set(ids) - set(existing):
        definition_error("fields", "Переданы повторные или чужие ID полей.")
    positions = [row["position"] for row in fields]
    if len(positions) != len(set(positions)):
        definition_error("fields", "Порядок полей не должен повторяться.")
    purposes = [row["purpose"] for row in fields if row["purpose"] != "other"]
    if len(purposes) != len(set(purposes)) or purposes.count("case") != 1:
        definition_error(
            "fields",
            "Нужен один выбор кейса или задачи; назначения не должны повторяться.",
        )
    candidates = {row["id"]: row for row in fields if row["id"] is not None}
    for row in fields:
        validate_definition(row)
        if row["type"] == "radio" and (
            row["id"] is None or existing[row["id"]].field_type != "radio"
        ):
            definition_error(
                "fields", "Новые поля radio не создаются. Используйте select.", row["id"]
            )
    for field_id, previous in existing.items():
        check_evolution(previous, candidates.get(field_id))
    removed = set(existing) - set(ids)
    # Пустые служебные записи не являются ответами и не мешают удалению определения.
    for field_id in removed:
        existing[field_id].solution_answers.all().delete()
    program.fields.filter(pk__in=removed).delete()
    # Освободить системное имя до изменения назначения незаполненного case.
    for field_id, candidate in candidates.items():
        if existing[field_id].name == "case" and candidate["purpose"] != "case":
            program.fields.filter(pk=field_id).update(name="solution_" + uuid4().hex)
    additions = []
    for position, candidate in enumerate(sorted(fields, key=lambda row: row["position"])):
        previous = existing.get(candidate["id"])
        values = dict(
            field_type=candidate["type"],
            purpose=candidate["purpose"],
            label=candidate["label"],
            help_text=candidate["help_text"],
            is_required=candidate["required"],
            position=position,
            validation=candidate["validation"],
            solution_options=candidate["options"],
            options="|".join(candidate["options"]),
            name="case"
            if candidate["purpose"] == "case"
            else previous.name
            if previous and previous.name != "case"
            else "solution_" + uuid4().hex,
            show_filter=candidate["purpose"] == "case",
        )
        if previous:
            program.fields.filter(pk=previous.pk).update(**values)
        else:
            additions.append(PartnerProgramField(partner_program=program, **values))
    PartnerProgramField.objects.bulk_create(additions)
    type(program).objects.filter(pk=program.pk).update(solution_template=template)
    program.solution_template = template
    return management_data(program)
