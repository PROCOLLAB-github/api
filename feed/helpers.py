import random
import typing

from feed import constants
from feed.serializers import FeedItemSerializer
from news.models import News
from projects.models import Project
from vacancy.models import Vacancy


def collect_feed() -> list:
    # да, это ужасно
    n_random_projects = get_n_random_projects(3)
    n_latest_created_projects = get_n_latest_created_projects(3)
    n_latest_created_news = get_n_latest_created_news(3)
    n_latest_created_vacancies = get_n_latest_created_vacancies(3)

    feed = [
        to_feed_items(
            constants.FeedItemType.PROJECT.value,
            set(n_random_projects + n_latest_created_projects),
        ),
        to_feed_items(constants.FeedItemType.NEWS.value, n_latest_created_news),
        to_feed_items(constants.FeedItemType.VACANCY.value, n_latest_created_vacancies),
    ]

    random.shuffle(feed)
    return feed


def to_feed_items(type_: constants.FeedItemType, items: typing.Iterable) -> list[dict]:
    feed_items = []
    for item in items:
        serializer = to_feed_item(type_, item)
        serializer.is_valid()
        feed_items += [serializer.data]
    return feed_items


def get_n_random_projects(num: int) -> list[Project]:
    tries = 3
    projects = set()

    while len(projects) < num and tries > 0:
        project = Project.objects.filter(draft=False).order_by("?").first()

        if project not in projects:
            projects.add(project)
        else:
            tries -= 1
    return list(projects)


def get_n_latest_created_projects(num: int) -> list[Project]:
    return list(Project.objects.filter(draft=False).order_by("-datetime_created")[:num])


def get_n_latest_created_news(num: int) -> list[Project]:
    return list(News.objects.order_by("-datetime_created")[:num])


def get_n_latest_created_vacancies(num: int) -> list[Project]:
    return list(Vacancy.objects.order_by("-datetime_created")[:num])


def to_feed_item(type_: constants.FeedItemType, data):
    serializer = constants.FEED_SERIALIZER_MAPPING[type_](data)

    return FeedItemSerializer(data={"type": type_, "content": serializer.data})
