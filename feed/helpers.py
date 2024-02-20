from random import shuffle
from typing import Iterable

from rest_framework.request import Request
from rest_framework.views import APIView

from feed import constants
from feed.constants import SupportedModel, SupportedQuerySet, LIMIT_PAGINATION_CONSTANT
from feed.pagination import FeedPagination
from feed.serializers import FeedItemSerializer
from news.models import News
from projects.models import Project

from django.db.models import Count

from vacancy.models import Vacancy


def add_pagination(results: list[SupportedQuerySet], count: int) -> dict:
    return {"count": count, "previous": None, "next": None, "results": results}


def paginate_serialize_feed(
    model_data: dict[SupportedQuerySet],
    paginator: FeedPagination,
    request: Request,
    view: APIView,
) -> tuple[list[SupportedQuerySet], int]:
    result = []
    pages_count = 0

    offset = request.query_params.get("offset", None)
    request.query_params._mutable = True

    if offset == "" or offset is None:
        offset = 0
    elif offset is not None:
        offset = int(offset)
        request.query_params["offset"] = offset


    offset_numbers = randomize_offset(offset, len(model_data.keys()))

    for i in range(len(model_data.keys())):
        request.query_params["offset"] = offset_numbers[i]
        paginated_part: dict = paginate_serialize_feed_queryset(
            model_data, paginator, request, list(model_data.keys())[i], view
        )
        result += paginated_part["paginated_data"]
        pages_count += paginated_part["page_count"]

    shuffle(result)

    limit = int(request.query_params.get("limit", LIMIT_PAGINATION_CONSTANT))
    if limit == "":
        limit = LIMIT_PAGINATION_CONSTANT
    return result[:limit], pages_count


def randomize_offset(offset: int, quantity_models: int) -> list[int]:
    full_division = offset // quantity_models
    extra_items = offset % quantity_models

    pagination_numbers = [full_division] * quantity_models
    pagination_numbers[-1] += extra_items

    return pagination_numbers


def paginate_serialize_feed_queryset(
    model_data: dict[SupportedQuerySet],
    paginator: FeedPagination,
    request: Request,
    model: SupportedModel,
    view: APIView,
) -> dict:
    paginated_info = paginator.custom_paginate_queryset(
        model_data[model], request, view=view
    )
    paginated_data = paginated_info["queryset_ready"]
    num_pages = paginated_info["count"]
    return {
        "paginated_data": to_feed_items(model, paginated_data),
        "page_count": num_pages,
    }


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
