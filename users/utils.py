import binascii
import os
from datetime import datetime, timedelta

from django.db.models import Q
from django.core.exceptions import ValidationError

import phonenumbers

from users.constants import NOT_VALID_NUMBER_MESSAGE


def filter_age(queryset, start: int, stop: int):
    """Filters given queryset by age range

    Args:
        queryset (_type_): Queryset of CustomUser
        start (int): start age, included
        stop (int): end age range, included

    Returns:
        Queryset: Filtered queryset of users
    """
    start, stop = min(start, stop), max(start, stop)
    return queryset.filter(
        Q(birthday__gte=datetime.now() - timedelta(days=365.24 * int(stop)))
        & Q(birthday__lte=datetime.now() - timedelta(days=365.24 * int(start)))
    )


def normalize_user_phone(phone_num: str):
    """Normalize phone number accoerding international standart."""
    try:
        phone_number = phonenumbers.parse(phone_num, None)
        if phonenumbers.is_valid_number(phone_number):
            return phonenumbers.format_number(
                phone_number, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
        raise ValidationError(NOT_VALID_NUMBER_MESSAGE)
    except phonenumbers.phonenumberutil.NumberParseException:
        raise ValidationError(NOT_VALID_NUMBER_MESSAGE)


def random_bytes_in_hex(count: int) -> str:
    """Генерация случайных байтов в формате hex."""
    try:
        random_bytes = os.urandom(count)
        return binascii.hexlify(random_bytes).decode()
    except Exception as e:
        raise ValueError(f"Could not generate {count} random bytes: {e}")
