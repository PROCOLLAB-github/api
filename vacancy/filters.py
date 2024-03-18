from django_filters import rest_framework as filters

from vacancy.models import Vacancy


def project_id_filter(queryset, name, value) -> queryset:
    return queryset.filter(
        **{
            "project_id": value[0],
        }
    )


class VacancyFilter(filters.FilterSet):
    """Filter for Vacancies

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        project_id (int), is_active (default to True if not set otherwise) (boolean)

    Examples:
        ?project_id=1 equals to .filter(project_id=1)
        (no params passed) equals to .filter(is_active=True)
        ?is_active=false equals to .filter(is_active=False)
    """

    def init(self, *args, **kwargs):
        """if is_active filter is not passed, default to True"""
        super().init(*args, **kwargs)
        if self.data.get("is_active") is None:
            self.data = dict(self.data)
            self.data["is_active"] = True

    is_active = filters.BooleanFilter(field_name="is_active")
    project_id = filters.Filter(method=project_id_filter)

    class Meta:
        model = Vacancy
        fields = ("project_id", "is_active")