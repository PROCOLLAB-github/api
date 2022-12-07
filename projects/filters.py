from django.db.models import Count
from django_filters import rest_framework as filters

from projects.models import Project


class ProjectFilter(filters.FilterSet):
    """Filter for Projects

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        industry (int), step (int), region (str), name__contains (str),
         description__contains (str), collaborator__user__in (List[int]),
         datetime_created__gt (datetime.datetime), step (int), any_vacancies (bool),
         member_count__gt (int), member_count__lt (int), leader (int)

    Examples:
        ?industry=1&name__contains=clown
            equals to .filter(industry=1, name__contains='clown')
        ?datetime_created__gt=25.10.2022
            equals to .filter(datetime_created__gt=datetime.datetime(...))
        ?collaborator__user__in=1,2 equals to .filter(collaborator__user__in=[1, 2])
        ?step=1 equals to .filter(step=1)
        ?any_vacancies=true equals to .filter(any_vacancies=True)
        ?collaborator__count__gt=1 equals to .filter(collaborator__count__gt=1)
    """

    @classmethod
    def filter_collaborator_count_lt(cls, queryset, name, value):
        return queryset.alias(Count("collaborator")).filter(collaborator__count__lt=value)

    @classmethod
    def filter_collaborator_count_gt(cls, queryset, name, value):
        return queryset.alias(Count("collaborator")).filter(collaborator__count__gt=value)

    name__contains = filters.Filter(field_name="name", lookup_expr="contains")
    description__contains = filters.Filter(
        field_name="description", lookup_expr="contains"
    )
    collaborator__user__in = filters.BaseInFilter(
        field_name="collaborator__user", lookup_expr="in"
    )
    datetime_created__gt = filters.DateTimeFilter(
        field_name="datetime_created", lookup_expr="gt"
    )

    # filters by whether there are any vacancies in the project
    any_vacancies = filters.BooleanFilter(
        field_name="vacancies", lookup_expr="isnull", exclude=True
    )
    collaborator__count__gt = filters.NumberFilter(
        field_name="collaborator", method="filter_collaborator_count_gt"
    )
    collaborator__count__lt = filters.NumberFilter(
        field_name="collaborator", method="filter_collaborator_count_lt"
    )
    step = filters.NumberFilter(field_name="step")

    class Meta:
        model = Project
        fields = ("industry", "step", "region", "leader", "step")
