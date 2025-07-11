from rest_framework.serializers import ValidationError


def validate_project(data):
    if not data.get("draft"):
        error = {}
        allowed_blank = {"image_address"}
        for key, value in data.items():
            if (value == "" or value is None) and key not in allowed_blank:
                error[key] = "This field is required"
        if error:
            raise ValidationError(error)
    return data
