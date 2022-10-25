from django_filters import rest_framework as filters

from news.models import News


class NewsFilter(filters.FilterSet):
    """
    Filter for News

    ?title__contains=clown - equal to .filter(title__contains='clown')
    ?text__contains=clown - equal to .filter(text__contains='clown')
    ?datetime_created__gt=01.01.2023 - equal to .filter(datetime_created__gt=01.01.2023)
    """

    title__contains = filters.Filter(field_name='title', lookup_expr='contains')
    text__contains = filters.Filter(field_name='text', lookup_expr='contains')
    datetime_created__gt = filters.DateTimeFilter(field_name='datetime_created', lookup_expr='gt')

    class Meta:
        model = News
        fields = ('title__contains', 'text__contains', 'datetime_created__gt')
