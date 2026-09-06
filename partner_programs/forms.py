"""Admin integration uses ordinary ModelForm validation, not a separate Case admin."""

from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from partner_programs.services.case_fields import case_field_has_values
from partner_programs.services.field_values import (
    FIELD_VALUES_FROZEN_MESSAGE,
    program_field_values_are_frozen,
)


class ProgramFieldInlineFormSet(BaseInlineFormSet):
    """Do not cascade-delete used case values through a definition inline."""

    def clean(self):
        super().clean()
        for form in self.deleted_forms:
            if case_field_has_values(form.instance):
                raise ValidationError(
                    "Нельзя удалить системное поле с выбранными кейсами."
                )


class ProgramFieldValueInlineFormSet(BaseInlineFormSet):
    """Admin skips model errors on DELETE forms, so enforce frozen deletion here."""

    def clean(self):
        super().clean()
        if any(form.instance.pk for form in self.deleted_forms):
            if program_field_values_are_frozen(self.instance):
                raise ValidationError(FIELD_VALUES_FROZEN_MESSAGE)
