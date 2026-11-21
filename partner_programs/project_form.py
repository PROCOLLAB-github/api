"""The form of a Project copy belongs to its program."""

from django.core.exceptions import ValidationError

from partner_programs.constants import PROGRAM_CASE_FIELD_NAME

PROJECT_SECTIONS = ("partners", "achievements", "vacancies", "program_data")
PROJECT_FIELDS = {
    "project_description": "description",
    "project_presentation": "presentation_address",
}


def project_sections(program):
    return {key: program.project_sections.get(key, True) for key in PROJECT_SECTIONS}


def visible_project_fields(program):
    fields = program.fields.filter(is_visible=True).order_by("pk")
    if not project_sections(program)["program_data"]:
        fields = fields.filter(name__in=(PROGRAM_CASE_FIELD_NAME, "project_description"))
    return fields


def field_value(link, field, values):
    attribute = PROJECT_FIELDS.get(field.name)
    return getattr(link.project, attribute) if attribute else values.get(field.pk)


def protected_project_field(field):
    return (
        field.name in PROJECT_FIELDS
        or field.values.filter(value_text__regex=r"\S").exists()
    )


def validate_project_field_evolution(previous, *, program_id, field_type, options):
    """Preserve the program, type and selected option of saved project answers."""
    if program_id != previous.partner_program_id and (
        previous.values.exists() or previous.solution_answers.exists()
    ):
        raise ValidationError(
            {"partner_program": "Нельзя переносить поле с ответами в другую программу."}
        )
    if not previous.values.filter(value_text__regex=r"\S").exists():
        return
    if field_type != previous.field_type:
        raise ValidationError({"field_type": "Нельзя изменить тип поля с ответами."})
    if field_type in ("select", "radio"):
        used = previous.values.exclude(value_text="").values_list(
            "value_text", flat=True
        ).distinct()
        if any(value not in options for value in used):
            raise ValidationError(
                {
                    "options": "Нельзя удалить или переименовать использованный вариант ответа."
                }
            )
