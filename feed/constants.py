import enum

from django.db.models import QuerySet
from rest_framework import serializers

from news.models import News
from news.serializers import NewsFeedListSerializer
from projects.models import Project
from projects.serializers import ProjectListSerializer
from vacancy.models import Vacancy
from vacancy.serializers import VacancyDetailSerializer


class FeedItemType(enum.Enum):
    PROJECT = "Project"
    NEWS = "News"
    VACANCY = "Vacancy"


FEED_SERIALIZER_MAPPING: dict[FeedItemType, serializers.Serializer] = {
    FeedItemType.PROJECT.value: ProjectListSerializer,
    FeedItemType.NEWS.value: NewsFeedListSerializer,
    FeedItemType.VACANCY.value: VacancyDetailSerializer,
}

SupportedModel = News | Project | Vacancy
SupportedQuerySet = QuerySet[News | Project | Vacancy]

model_mapping = {"news": News, "project": Project, "vacancy": Vacancy}