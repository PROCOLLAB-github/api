"""Freeze mutations, not revalidation of unchanged model/admin inline values."""

from django.core.exceptions import ValidationError

from partner_programs.models import PartnerProgramProject


FIELD_VALUES_FROZEN_MESSAGE = (
    "Нельзя изменять значения полей программы после сдачи проекта на проверку."
)


def program_field_values_are_frozen(program_project):
    """Either persisted submission or a pending parent-form submission freezes edits.

    The admin validates inlines before saving the parent, so DB state alone misses
    simultaneous submit/edit; the in-memory flag alone permits unsubmit/edit or
    writes using a stale parent instance.
    """
    pending_submission = (
        program_project.submitted
        and program_project.partner_program_id
        and program_project.partner_program.is_competitive
    )
    return (
        bool(pending_submission)
        or PartnerProgramProject.objects.filter(
            pk=program_project.pk,
            submitted=True,
            partner_program__is_competitive=True,
        ).exists()
    )


def validate_field_value_mutation(value):
    """Validate freeze rules and return whether the persisted answer would change."""
    fields = ("program_project_id", "field_id", "value_text")
    persisted = (
        type(value).objects.filter(pk=value.pk).values(*fields).first()
        if value.pk is not None
        else None
    )
    if (
        not value._state.adding
        and persisted is not None
        and all(persisted[name] == getattr(value, name) for name in fields)
    ):
        return False

    # Moving a persisted value out of a frozen link must not bypass its freeze.
    frozen_source = (
        persisted is not None
        and persisted["program_project_id"] != value.program_project_id
        and PartnerProgramProject.objects.filter(
            pk=persisted["program_project_id"],
            submitted=True,
            partner_program__is_competitive=True,
        ).exists()
    )
    if frozen_source or program_field_values_are_frozen(value.program_project):
        raise ValidationError(FIELD_VALUES_FROZEN_MESSAGE)
    return True


def validate_project_choice_value(field, value):
    """Validate the exact stored value against a legacy select or radio definition."""
    field_type = field.field_type
    options = field.get_options_list()
    if not options:
        raise ValidationError(
            f"Для поля типа '{field_type}' не заданы допустимые значения."
        )
    if value is None or value == "":
        if field.is_required:
            raise ValidationError(
                f"Значение обязательно для поля типа '{field_type}'."
            )
        return
    if not isinstance(value, str):
        raise ValidationError(
            f"Ожидается строковое значение для поля типа '{field_type}'."
        )
    if value not in options:
        raise ValidationError(
            f"Недопустимое значение для поля типа '{field_type}'. "
            f"Ожидается одно из: {options}."
        )
