import random
from typing import Iterable

from rest_framework.pagination import LimitOffsetPagination

from feed import constants
from feed.constants import SupportedModel, SupportedQuerySet
from feed.serializers import FeedItemSerializer
from news.models import News
from projects.models import Project

from django.db.models import Count

from vacancy.models import Vacancy


def add_pagination(results: list[SupportedQuerySet], count: int) -> dict:
    return {"count": count, "previous": None, "next": None, "results": results}


def paginate_serialize_feed(
    model_data: dict[SupportedQuerySet], paginator: LimitOffsetPagination, request, view
) -> tuple[list[SupportedQuerySet], int]:
    result = []
    sum_num_pages = 0
    for model in model_data:
        sum_num_pages += paginate_serialize_feed_queryset(
            model_data, paginator, request, model, view, result
        )
    random.shuffle(result)
    limit = (
        int(request.query_params.get("limit"))
        if request.query_params.get("limit")
        else 10
    )
    return result[:limit], sum_num_pages


def paginate_serialize_feed_queryset(
    model_data: dict[SupportedQuerySet],
    paginator: LimitOffsetPagination,
    request,
    model,
    view,
    result: list[SupportedQuerySet],
) -> int:
    num_pages = paginator.get_count(model_data[model])
    paginated_data = paginator.paginate_queryset(model_data[model], request, view=view)
    result.extend(to_feed_items(model, paginated_data))
    return num_pages


def collect_querysets(model: SupportedModel) -> SupportedQuerySet:
    if model == Project:
        queryset = model.objects.select_related("leader", "industry").filter(draft=False)
    elif model == Vacancy:
        queryset = model.objects.select_related("project")
    elif model == News:
        queryset = (
            model.objects.select_related("content_type")
            .prefetch_related("content_object", "files")
            .annotate(likes_count=Count("likes"), views_count=Count("views"))
        )

    return queryset.order_by("-datetime_created")


def to_feed_items(type_: constants.FeedItemType, items: Iterable) -> list[dict]:
    feed_items = []
    for item in items:
        serializer = to_feed_item(type_, item)
        serializer.is_valid()
        feed_items += [serializer.data]
    return feed_items


def to_feed_item(type_: constants.FeedItemType, data):
    serializer = constants.FEED_SERIALIZER_MAPPING[type_](data)
    return FeedItemSerializer(data={"type_model": type_, "content": serializer.data})
