from typing import Iterable

from feed import constants
from feed.constants import SupportedModel, SupportedQuerySet
from feed.serializers import FeedItemSerializer
from news.models import News
from projects.models import Project

from django.core.paginator import Paginator
from django.db.models import Count

from vacancy.models import Vacancy


def add_pagination(queryset: list[dict], count: int) -> dict:
    return {"count": count, "results": queryset, "next": "0", "previous": "0"}


def paginate_model_items(
    queryset: SupportedQuerySet, page_num: int
) -> tuple[list[SupportedQuerySet], int]:
    paginator = Paginator(queryset, 3)
    page_obj = paginator.get_page(page_num)
    total_pages = paginator.num_pages
    return page_obj.object_list, total_pages


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
