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
    """Compare persisted identity/content; new, moved or changed values are mutations."""
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
        return

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
