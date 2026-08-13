from django.db.models import Q, QuerySet

from django_filters import rest_framework as filters

from vacancy.models import Vacancy
from vacancy.constants import (
    WorkExperience,
    WorkSchedule,
    WorkFormat,
)


def project_id_filter(queryset, name, value) -> QuerySet:
    return queryset.filter(project_id=value)


class VacancyFilter(filters.FilterSet):
    """Фильтрует уже ограниченный безопасный queryset публичного каталога."""

    def filter_by_experience(
        self, queryset: QuerySet[Vacancy], name, value: list[str]
    ) -> QuerySet[Vacancy]:
        return queryset.filter(required_experience__in=value)

    def filter_by_schedule(
        self, queryset: QuerySet[Vacancy], name, value: list[str]
    ) -> QuerySet[Vacancy]:
        return queryset.filter(work_schedule__in=value)

    def filter_by_format(
        self, queryset: QuerySet[Vacancy], name, value: list[str]
    ) -> QuerySet[Vacancy]:
        return queryset.filter(work_format__in=value)

    def filter_by_salary_min(
        self, queryset: QuerySet[Vacancy], name, value: str
    ) -> QuerySet[Vacancy]:
        try:
            min_salary = int(value)
            return queryset.filter(salary__gte=min_salary)
        except (TypeError, ValueError):
            return queryset

    def filter_by_salary_max(
        self, queryset: QuerySet[Vacancy], name, value: str
    ) -> QuerySet[Vacancy]:
        try:
            max_salary = int(value)
            return queryset.filter(salary__lte=max_salary)
        except (TypeError, ValueError):
            return queryset

    def filter_by_role(
        self, queryset: QuerySet[Vacancy], name, value: str
    ) -> QuerySet[Vacancy]:
        return queryset.filter(role__icontains=value)

    def filter_by_search(self, queryset, name, value):
        """Ищет вакансию по роли, специализации, описанию и названию проекта."""

        search = value.strip()
        if not search:
            return queryset
        return queryset.filter(
            Q(role__icontains=search)
            | Q(specialization__icontains=search)
            | Q(description__icontains=search)
            | Q(project__name__icontains=search)
        )

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
    search = filters.CharFilter(method="filter_by_search")
    salary_min = filters.Filter(method="filter_by_salary_min")
    salary_max = filters.Filter(method="filter_by_salary_max")

    class Meta:
        model = Vacancy
        fields = (
            "role_contains",
            "search",
            "project_id",
            "is_active",
            "required_experience",
            "work_schedule",
            "work_format",
            "salary_min",
            "salary_max",
        )
