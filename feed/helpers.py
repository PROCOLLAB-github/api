from random import shuffle
from typing import Iterable

from rest_framework.request import Request
from rest_framework.views import APIView

from feed import constants
from feed.constants import (
    SupportedModel,
    SupportedQuerySet,
    LIMIT_PAGINATION_CONSTANT
)
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

    if len(model_data) == 0:
        return [], 0

    offset = request.query_params.get("offset", 0)
    request.query_params._mutable = True

    if isinstance(offset, str) and offset.isdigit():
        offset = int(offset)
    else:
        offset = 0

    request.query_params["offset"] = offset

    models_counts = {
        model_name: model_data[model_name].count() for model_name in model_data.keys()
    }
    offset_numbers = offset_distribution(offset, models_counts)

    for model_name in model_data.keys():
        request.query_params["offset"] = offset_numbers[model_name]

        paginated_part: dict = paginate_serialize_feed_queryset(
            model_data, paginator, request, model_name, models_counts[model_name], view
        )

        result += paginated_part["paginated_data"]
        pages_count += paginated_part["page_count"]

    limit = request.query_params.get("limit", LIMIT_PAGINATION_CONSTANT)

    if limit == "":
        limit = LIMIT_PAGINATION_CONSTANT
    else:
        limit = int(limit)

    shuffle(result)
    return result[:limit], pages_count


def offset_distribution(offset: int, models_counts: dict) -> dict:
    common_key_list = list(models_counts.keys())
    quantity_of_models = len(list(models_counts.keys()))

    full_division = offset // quantity_of_models
    extra_items = offset % quantity_of_models

    distributed_not_ready = {model_name: full_division for model_name in common_key_list}
    distributed = dict(
        sorted(distributed_not_ready.items(), key=lambda item: models_counts[item[0]])
    )

    last_key = common_key_list[-1]
    distributed[last_key] += extra_items

    new_keys_list = list(distributed.keys())
    for i, key in enumerate(
        new_keys_list
    ):  # распределяем переполненные значения от маленьких моделей к большим
        offset_value = distributed[key]
        model_count = models_counts[key]
        if offset_value > model_count:
            diff = offset_value - model_count
            distributed[key] = model_count
            if i + 1 < len(new_keys_list):
                next_key = new_keys_list[i + 1]
                distributed[next_key] += diff

    return distributed


def paginate_serialize_feed_queryset(
    model_data: dict[SupportedQuerySet],
    paginator: FeedPagination,
    request: Request,
    model: SupportedModel,
    count: int,
    view: APIView,
) -> dict:
    paginated_info = paginator.custom_paginate_queryset(
        model_data[model], request, count, view=view
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
