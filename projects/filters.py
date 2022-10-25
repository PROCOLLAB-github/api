from django_filters import rest_framework as filters

from projects.models import Project


class ProjectFilter(filters.FilterSet):
    """
    Filter for Projects

    ?industry=1 - equal to .filter(industry=1)
    ?step=1 - equal to .filter(step=1)
    ?name__contains=clown - equal to .filter(name__contains='clown')
    ?collaborators__in=1,2,3 - equal to .filter(collaborators__in=[1, 2, 3])
    ?datetime_created__gt=01.01.2023 - equal to .filter(datetime_created__gt=01.01.2023)
    """

    name__contains = filters.Filter(field_name='name', lookup_expr='contains')
    description__contains = filters.Filter(field_name='name', lookup_expr='contains')
    region = filters.CharFilter(field_name='region')
    collaborators__in = filters.BaseInFilter(field_name='collaborators')
    datetime_created__gt = filters.DateTimeFilter(field_name='datetime_created', lookup_expr='gt')

    class Meta:
        model = Project
        fields = ('industry', 'step')
