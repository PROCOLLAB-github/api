from django.utils import timezone
from django.core.exceptions import ValidationError


def user_birthday_validator(birthday):
    """returns true if person > 14 years old"""
    if (timezone.now().date() - birthday).days >= 14 * 365:
        return True
    raise ValidationError("Человек младше 14 лет")
