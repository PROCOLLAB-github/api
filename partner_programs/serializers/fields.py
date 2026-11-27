from urllib.parse import urlparse

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from partner_programs.models import PartnerProgramField
from partner_programs.services.field_values import validate_project_choice_value


class ProgramFieldReference(serializers.PrimaryKeyRelatedField):
    """Resolve input ids within the URL program before revealing field validation."""

    def get_queryset(self):
        queryset = super().get_queryset()
        program = self.context.get("program")
        return (
            queryset.filter(partner_program=program) if program is not None else queryset
        )


class PartnerProgramFieldValueUpdateSerializer(serializers.Serializer):
    field_id = ProgramFieldReference(
        queryset=PartnerProgramField.objects.all(),
        source="field",
    )
    value_text = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Укажите значение для поля.",
    )

    def validate(self, attrs):
        field = attrs.get("field")
        value_text = attrs.get("value_text")

        if self.context.get("allow_incomplete") and (
            value_text is None or not str(value_text).strip()
        ):
            attrs["value_text"] = ""
            return attrs

        validator = self._get_validator(field)
        validator(field, value_text, attrs)

        return attrs

    def _get_validator(self, field: PartnerProgramField):
        validators = {
            "text": self._validate_text,
            "textarea": self._validate_text,
            "checkbox": self._validate_checkbox,
            "select": self._validate_choice,
            "radio": self._validate_choice,
            "file": self._validate_file,
            "url": self._validate_file,
        }
        try:
            return validators[field.field_type]
        except KeyError:
            raise serializers.ValidationError(
                f"Тип поля '{field.field_type}' не поддерживается."
            )

    def _validate_text(self, field: PartnerProgramField, value, attrs):
        if field.is_required:
            if value is None or str(value).strip() == "":
                raise serializers.ValidationError(
                    "Поле должно содержать текстовое значение."
                )
        else:
            if value is not None and not isinstance(value, str):
                raise serializers.ValidationError("Ожидается строка для текстового поля.")

    def _validate_checkbox(self, field: PartnerProgramField, value, attrs):
        if field.is_required and value in (None, ""):
            raise serializers.ValidationError(
                "Значение обязательно для поля типа 'checkbox'."
            )

        if value is not None:
            if isinstance(value, bool):
                attrs["value_text"] = "true" if value else "false"
            elif isinstance(value, str):
                normalized = value.strip().lower()
                if normalized not in ("true", "false"):
                    raise serializers.ValidationError(
                        "Для поля типа 'checkbox' ожидается 'true' или 'false'."
                    )
                attrs["value_text"] = normalized
            else:
                raise serializers.ValidationError(
                    "Неверный тип значения для поля 'checkbox'."
                )

    def _validate_choice(self, field: PartnerProgramField, value, attrs):
        try:
            validate_project_choice_value(field, value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages[0]) from error

    def _validate_file(self, field: PartnerProgramField, value, attrs):
        if field.is_required:
            if value is None or value == "":
                raise serializers.ValidationError("Файл обязателен для этого поля.")

        if value is not None:
            if not isinstance(value, str):
                raise serializers.ValidationError(
                    "Ожидается строковое значение для поля 'file'."
                )

            if not self._is_valid_url(value):
                raise serializers.ValidationError(
                    "Ожидается корректная ссылка (URL) на файл."
                )

    def _is_valid_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False
