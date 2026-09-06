"""Admin integration uses ordinary ModelForm validation, not a separate Case admin."""

from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from partner_programs.services.case_fields import case_field_has_values


class ProgramFieldInlineFormSet(BaseInlineFormSet):
    """Do not cascade-delete used case values through a definition inline."""

    def clean(self):
        super().clean()
        for form in self.deleted_forms:
            if case_field_has_values(form.instance):
                raise ValidationError(
                    "Нельзя удалить системное поле с выбранными кейсами."
                )
