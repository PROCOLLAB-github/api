from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError

import phonenumbers

from users.constants import NOT_VALID_NUMBER_MESSAGE


def user_birthday_validator(birthday):
    """returns true if person > 12 years old"""
    if (timezone.now().date() - birthday).days >= 12 * 365:
        return True
    # check if person is > 100 years old
    if (timezone.now().date() - birthday).days >= 100 * 365:
        raise ValidationError("Человек старше 100 лет")
    raise ValidationError("Человек младше 12 лет")


def user_name_validator(name):
    """returns true if name is valid"""
    # TODO: add check for vulgar words

    valid_name_chars = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    for letter in name:
        if letter.upper() not in valid_name_chars:
            raise ValidationError(
                "Имя содержит недопустимые символы. Могут быть только символы кириллического алфавита."
            )
    if len(name) < 2:
        raise ValidationError("Имя слишком короткое")
    return True


def specialization_exists_validator(pk: int):
    # avoid circular imports
    from core.models import Specialization

    if not Specialization.objects.filter(pk=pk).exists():
        raise serializers.ValidationError(
            {"v2_speciality_id": "Specialization with given id does not exist"}
        )


def user_experience_years_range_validator(value: int):
    """
    Check range for choice entry/completion year.
    (2000 - `now.year`)
    """
    if value not in range(2000, timezone.now().year + 1):
        raise DjangoValidationError(f"Год должен быть в диапазоне 2000 - {timezone.now().year}")


def user_phone_number_validation(value: str):
    """Validates phone number according to the international standard."""
    try:
        phone_number = phonenumbers.parse(value, None)
        return phonenumbers.is_valid_number(phone_number)
    except phonenumbers.phonenumberutil.NumberParseException:
        raise DjangoValidationError(NOT_VALID_NUMBER_MESSAGE)
