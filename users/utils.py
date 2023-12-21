from datetime import datetime, timedelta
from django.db.models import Q


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
