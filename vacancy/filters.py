from django.db.models import QuerySet, Q, F

from django_filters import rest_framework as filters

from vacancy.models import Vacancy
from vacancy.constants import (
    WorkExperience,
    WorkSchedule,
    WorkFormat,
)


def project_id_filter(queryset, name, value) -> QuerySet:
    return queryset.filter(
        **{
            "project_id": value[0],
        }
    )


class VacancyFilter(filters.FilterSet):
    """Filter for Vacancies

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        project_id (int),
        is_active (boolean) (default to True if not set otherwise),
        required_experience (multiple choise)
        work_schedule (multiple choise)
        work_format (multiple choise)
        salary_min (int)
        salary_max (int)

    Examples:
        ?project_id=1 equals to .filter(project_id=1)
        (no params passed) equals to .filter(is_active=True)
        ?is_active=false equals to .filter(is_active=False)
        ?work_schedule=full_time&work_schedule=part_time equals to .filter(required_experience__in=value)
        ?salary_min=100&salary_max=150 equals to .filter(salary__range=(100, 150))
    """

    def __init__(self, *args, **kwargs):
        """if is_active filter is not passed, default to True"""
        super().__init__(*args, **kwargs)
        if self.data.get("is_active") is None:
            self.data = dict(self.data)
            self.data["is_active"] = True

    def filter_by_experience(self, queryset: QuerySet[Vacancy], name, value: list[str]) -> QuerySet[Vacancy]:
        return (
            queryset
            .filter(Q(required_experience__in=value) | Q(required_experience=None))
            .order_by(F("required_experience").asc(nulls_last=True))
        )

    def filter_by_schedule(self, queryset: QuerySet[Vacancy], name, value: list[str]) -> QuerySet[Vacancy]:
        return (
            queryset
            .filter(Q(work_schedule__in=value) | Q(work_schedule=None))
            .order_by(F("work_schedule").asc(nulls_last=True))
        )

    def filter_by_format(self, queryset: QuerySet[Vacancy], name, value: list[str]) -> QuerySet[Vacancy]:
        return (
            queryset
            .filter(Q(work_format__in=value) | Q(work_format=None))
            .order_by(F("work_format").asc(nulls_last=True))
        )

    def filter_by_salary_min(self, queryset: QuerySet[Vacancy], name, value: list[str]) -> QuerySet[Vacancy]:
        try:
            min_salary = int(value[0])
            return (
                queryset
                .filter(Q(salary__gte=min_salary) | Q(salary=None))
                .order_by(F("salary").asc(nulls_last=True))
            )
        except ValueError:
            return queryset

    def filter_by_salary_max(self, queryset: QuerySet[Vacancy], name, value: list[str]) -> QuerySet[Vacancy]:
        try:
            max_salary = int(value[0])
            return (
                queryset
                .filter(Q(salary__lte=max_salary) | Q(salary=None))
                .order_by(F("salary").asc(nulls_last=True))
            )
        except ValueError:
            return queryset

    def filter_by_role(self, queryset: QuerySet[Vacancy], name, value: list[str]) -> QuerySet[Vacancy]:
        if not value:
            return queryset
        return queryset.filter(role__icontains=value[0])

    project_id = filters.Filter(method=project_id_filter)
    is_active = filters.BooleanFilter(field_name="is_active")

    required_experience = filters.MultipleChoiceFilter(
        method="filter_by_experience",
        choices=WorkExperience.choices(),
    )
    work_schedule = filters.MultipleChoiceFilter(
        method="filter_by_schedule",
        choices=WorkSchedule.choices(),
    )
    work_format = filters.MultipleChoiceFilter(
        method="filter_by_format",
        choices=WorkFormat.choices(),
    )

    role_contains = filters.Filter(method="filter_by_role")
    salary_min = filters.Filter(method="filter_by_salary_min")
    salary_max = filters.Filter(method="filter_by_salary_max")

    class Meta:
        model = Vacancy
        fields = (
            "role_contains",
            "project_id",
            "is_active",
            "required_experience",
            "work_schedule",
            "work_format",
            "salary_min",
            "salary_max",
        )
