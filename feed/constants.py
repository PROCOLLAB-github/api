import enum

from rest_framework import serializers

from news.serializers import NewsListSerializer
from projects.serializers import ProjectListSerializer
from vacancy.serializers import VacancyDetailSerializer


class FeedItemType(enum.Enum):
    PROJECT = "Project"
    NEWS = "News"
    VACANCY = "Vacancy"


FEED_SERIALIZER_MAPPING: dict[FeedItemType, serializers.Serializer] = {
    FeedItemType.PROJECT.value: ProjectListSerializer,
    FeedItemType.NEWS.value: NewsListSerializer,
    FeedItemType.VACANCY.value: VacancyDetailSerializer,
}
