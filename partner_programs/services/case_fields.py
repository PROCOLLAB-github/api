"""Reserved case semantics on existing program fields, never on global Project."""

from django.core.exceptions import ValidationError

from partner_programs.constants import PROGRAM_CASE_FIELD_NAME


def is_program_case_field(field):
    """Only the exact service name identifies a case; label/type are not heuristics."""
    return field.name == PROGRAM_CASE_FIELD_NAME


def get_program_case_field(program, *, for_update=False):
    """Return the optional definition; absence does not enable case requirements."""
    fields = program.fields.filter(name=PROGRAM_CASE_FIELD_NAME)
    if for_update:
        fields = fields.select_for_update()
    return fields.first()


def case_field_has_values(field):
    """Use persisted identity, including when an admin form edits name before deletion."""
    if not field.pk:
        return False
    return (
        type(field)
        .objects.filter(pk=field.pk, name=PROGRAM_CASE_FIELD_NAME, values__isnull=False)
        .exists()
    )


def validate_program_case_configuration(field):
    """Validate select-only config and preserve every used exact textual option."""
    previous = type(field).objects.filter(pk=field.pk).first() if field.pk else None
    if previous and is_program_case_field(previous) and previous.values.exists():
        if field.name != previous.name:
            raise ValidationError(
                {"name": "Нельзя переименовать системное поле с выбранными кейсами."}
            )
        if field.partner_program_id != previous.partner_program_id:
            raise ValidationError(
                {"partner_program": "Нельзя переносить поле с выбранными кейсами."}
            )

    if not is_program_case_field(field):
        return
    errors = {}
    if field.field_type != "select":
        errors["field_type"] = "Системный кейс должен быть полем select."
    if not field.is_required:
        errors["is_required"] = "Кейс обязателен перед сдачей проекта."
    if not field.show_filter:
        errors["show_filter"] = "Системный кейс должен быть доступен для фильтрации."
    options = [value.strip() for value in (field.options or "").split("|")]
    if not all(options):
        errors["options"] = "Укажите хотя бы один кейс без пустых вариантов."
    elif len({value.casefold() for value in options}) != len(options):
        errors[
            "options"
        ] = "Варианты кейсов не должны повторяться (без учёта регистра и внешних пробелов)."
    if field.pk:
        used = set(field.values.values_list("value_text", flat=True).distinct())
        if used - set(options):
            errors["options"] = "Нельзя удалить или переименовать используемый кейс."
    if errors:
        raise ValidationError(errors)


def validate_case_value(field, value):
    """Validate an explicit choice against the current exact options, without guessing."""
    if value is None or not str(value).strip():
        raise ValidationError("Выберите кейс перед сдачей проекта.")
    if value not in field.get_options_list():
        raise ValidationError(
            "Выбранный кейс больше недоступен. Выберите актуальный кейс."
        )


def validate_case_before_submission(program_project):
    """Lock config inside the caller's transaction; validate this link only."""
    field = get_program_case_field(program_project.partner_program, for_update=True)
    if field is None:
        return
    value = (
        program_project.field_values.filter(field=field)
        .values_list("value_text", flat=True)
        .first()
    )
    validate_case_value(field, value)
