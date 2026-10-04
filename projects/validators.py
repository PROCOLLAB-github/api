from django.core.validators import RegexValidator
from rest_framework.serializers import ValidationError

from projects.names import normalize_project_name


def validate_project(data):
    if "name" in data:
        data["name"] = normalize_project_name(data["name"])

    if not data.get("draft"):
        error = {}
        allowed_blank = {"image_address"}
        for key, value in data.items():
            if (value == "" or value is None) and key not in allowed_blank:
                error[key] = "This field is required"
        if error:
            raise ValidationError(error)
    return data


inn_validator = RegexValidator(
    regex=r"^\d{10}(\d{2})?$",
    message="ИНН должен содержать 10 или 12 цифр.",
)
