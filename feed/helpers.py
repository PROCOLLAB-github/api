import random
import typing

from feed import constants
from feed.serializers import FeedItemSerializer
from projects.models import Project


def collect_feed(models_list: typing.List, num) -> list[dict]:
    get_model_data = {
        model.__name__: collect_querysets(model, num) for model in models_list
    }
    result = []
    for model in get_model_data:
        result.extend(to_feed_items(model, get_model_data[model]))
    random.shuffle(result)
    return result


def collect_querysets(model, num):
    if model.__name__ == Project.__class__.__name__:
        return set(get_n_random_projects(num) + get_n_latest_created_projects(num))
    else:
        return list(model.objects.order_by("-datetime_created")[:num])


def to_feed_items(type_: constants.FeedItemType, items: typing.Iterable) -> list[dict]:
    feed_items = []
    for item in items:
        serializer = to_feed_item(type_, item)
        serializer.is_valid()
        feed_items += [serializer.data]
    return feed_items


def get_n_random_projects(num: int) -> list[Project]:
    return list(Project.objects.filter(draft=False).order_by("?").distinct()[:num])


def get_n_latest_created_projects(num: int) -> list[Project]:
    return list(Project.objects.filter(draft=False).order_by("-datetime_created")[:num])


def to_feed_item(type_: constants.FeedItemType, data):
    serializer = constants.FEED_SERIALIZER_MAPPING[type_](data)
    return FeedItemSerializer(data={"type": type_, "content": serializer.data})
