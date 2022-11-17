from rest_framework.serializers import ValidationError


def validate_project(data):
    if not data.get("draft"):
        error = {}
        for key, value in data.items():
            if value == "" or value is None:
                error[key] = "This field is required"
        if error:
            raise ValidationError(error)
    return data
