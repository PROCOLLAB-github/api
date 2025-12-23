from urllib.parse import urlparse

from rest_framework import serializers

from partner_programs.models import PartnerProgramField


class PartnerProgramFieldValueUpdateSerializer(serializers.Serializer):
    field_id = serializers.PrimaryKeyRelatedField(
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

        validator = self._get_validator(field)
        validator(field, value_text, attrs)

        return attrs

    def _get_validator(self, field: PartnerProgramField):
        validators = {
            "text": self._validate_text,
            "textarea": self._validate_text,
            "checkbox": self._validate_checkbox,
            "select": self._validate_select,
            "radio": self._validate_radio,
            "file": self._validate_file,
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

    def _validate_select(self, field: PartnerProgramField, value, attrs):
        self._validate_choice_field(field, value, "select")

    def _validate_radio(self, field: PartnerProgramField, value, attrs):
        self._validate_choice_field(field, value, "radio")

    def _validate_choice_field(self, field: PartnerProgramField, value, field_type):
        options = field.get_options_list()

        if not options:
            raise serializers.ValidationError(
                f"Для поля типа '{field_type}' не заданы допустимые значения."
            )

        if field.is_required:
            if value is None or value == "":
                raise serializers.ValidationError(
                    f"Значение обязательно для поля типа '{field_type}'."
                )
        else:
            if value is None or value == "":
                return

        if value is not None:
            if not isinstance(value, str):
                raise serializers.ValidationError(
                    f"Ожидается строковое значение для поля типа '{field_type}'."
                )
            if value not in options:
                raise serializers.ValidationError(
                    f"Недопустимое значение для поля типа '{field_type}'. "
                    f"Ожидается одно из: {options}."
                )

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
