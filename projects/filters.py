from django_filters import rest_framework as filters

from projects.models import Project


class ProjectFilter(filters.FilterSet):
    """Filter for Projects

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        industry (int), step (int), region (str), name__contains (str),
         description__contains (str), collaborators__in (List[int]),
         datetime_created__gt (datetime.datetime)

    Examples:
        ?industry=1&name__contains=clown
            equals to .filter(industry=1, name__contains='clown')
        ?datetime_created__gt=25.10.2022
            equals to .filter(datetime_created__gt=datetime.datetime(...))
        ?collaborators__in=1,2 equals to .filter(collaborators__in=[1, 2])
    """

    name__contains = filters.Filter(field_name="name", lookup_expr="contains")
    description__contains = filters.Filter(
        field_name="description", lookup_expr="contains"
    )
    collaborators__in = filters.BaseInFilter(field_name="collaborators")
    datetime_created__gt = filters.DateTimeFilter(
        field_name="datetime_created", lookup_expr="gt"
    )

    class Meta:
        model = Project
        fields = ("industry", "step", "region")