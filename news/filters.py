from django_filters import rest_framework as filters

from news.models import News


class NewsFilter(filters.FilterSet):
    """Filter for News

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        title__contains (str), text__contains (str),
        datetime_created__gt (datetime.datetime)

    Examples:
        ?title__contains=test             equals to .filter(title__contains='test')
        ?datetime_created__gt=01.10.2022  equals to
            .filter(datetime_created__gt=datetime.datetime(...))
    """

    title__contains = filters.Filter(field_name="title", lookup_expr="contains")
    text__contains = filters.Filter(field_name="text", lookup_expr="contains")
    datetime_created__gt = filters.DateTimeFilter(
        field_name="datetime_created", lookup_expr="gt"
    )

    class Meta:
        model = News
        fields = ("title__contains", "text__contains", "datetime_created__gt")
