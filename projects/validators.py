from django.core.validators import RegexValidator

from projects.names import normalize_project_name


def validate_project(data):
    if "name" in data:
        data["name"] = normalize_project_name(data["name"])
    return data


inn_validator = RegexValidator(
    regex=r"^\d{10}(\d{2})?$",
    message="ИНН должен содержать 10 или 12 цифр.",
)
