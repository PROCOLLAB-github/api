from django.utils import timezone
from django.core.exceptions import ValidationError


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
