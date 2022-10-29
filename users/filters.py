from django_filters import rest_framework as filters

from users.models import CustomUser


class UserFilter(filters.FilterSet):
    """Filter for News

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        first_name (str), last_name (str), patronymic (str), specialty (str),
        city (str), region (str), organization (str), about_me__contains (str),
        key_skills__contains (str), useful_to_project__contains (str)

    Examples:
        ?first_name=test             equals to .filter(first_name='test')
        ?key_skills__contains=yawning  equals to .filter(key_skills__containing='yawning')

    """

    about_me__contains = filters.Filter(field_name="about_me", lookup_expr="contains")
    key_skills__contains = filters.Filter(field_name="key_skills", lookup_expr="contains")
    useful_to_project__contains = filters.Filter(
        field_name="useful_to_project", lookup_expr="contains"
    )

    class Meta:
        model = CustomUser
        fields = (
            "first_name",
            "last_name",
            "patronymic",
            "city",
            "region",
            "organization",
        )
