from django.db.models import Count, Q, QuerySet
from rest_framework.views import APIView

from feed.pagination import FeedPagination
from feed.services import get_liked_news
from news.models import News
from news.services import FEED_RECORD_TEXT
from projects.models import Project
from vacancy.models import Vacancy

from .serializers import FeedItemResponseSerializer


PROJECT_FEED = Q(content_type__model="project")
PROJECT_RECORD = Q(text=FEED_RECORD_TEXT)
PROJECT_NEWS = PROJECT_FEED & ~PROJECT_RECORD
NEW_PROJECTS = PROJECT_FEED & PROJECT_RECORD
COMMUNITY_NEWS = Q(content_type__model="customuser")
VACANCIES = Q(content_type__model="vacancy")

FEED_FILTERS = {
    "all_news": PROJECT_NEWS | COMMUNITY_NEWS,
    "project_news": PROJECT_NEWS,
    "news": COMMUNITY_NEWS,
    "vacancy": VACANCIES,
    "new_project": NEW_PROJECTS,
    # Existing clients still request the combined project category.
    "project": PROJECT_FEED,
    "customuser": COMMUNITY_NEWS,
}


class NewSimpleFeed(APIView):
    serializer_class = FeedItemResponseSerializer
    pagination_class = FeedPagination

    def get_visible_queryset(self) -> QuerySet[News]:
        queryset = News.objects.select_related("content_type").prefetch_related(
            "content_object", "files"
        )

        existing_object_filters = {
            "project": Project.objects.filter(draft=False, is_public=True).values_list(
                "id", flat=True
            ),
            "vacancy": Vacancy.objects.filter(
                is_active=True,
                project__draft=False,
                project__is_public=True,
            ).values_list("id", flat=True),
        }
        for model_name, ids_queryset in existing_object_filters.items():
            queryset = queryset.exclude(
                Q(content_type__model=model_name) & ~Q(object_id__in=ids_queryset)
            )

        return queryset

    def get_queryset(self) -> QuerySet[News]:
        filters = Q(pk__in=[])
        for category in self.request.query_params.get("type", "").split("|"):
            if category in FEED_FILTERS:
                filters |= FEED_FILTERS[category]

        return (
            self.get_visible_queryset()
            .filter(filters)
            .order_by("-datetime_created", "-pk")
        )

    def get_category_counts(self) -> dict[str, int]:
        # Программы и образование пока не включены в ленту; не считаем скрытый контент.
        counts = self.get_visible_queryset().aggregate(
            project_news=Count("pk", filter=PROJECT_NEWS),
            new_project=Count("pk", filter=NEW_PROJECTS),
            vacancy=Count("pk", filter=VACANCIES),
            news=Count("pk", filter=COMMUNITY_NEWS),
        )
        return {
            "all": sum(counts.values()),
            "all_news": counts["project_news"] + counts["news"],
            "project": counts["project_news"] + counts["new_project"],
            **counts,
            "partnerprogram": 0,
            "education": 0,
        }

    def get(self, *args, **kwargs):
        paginator = self.pagination_class()
        paginated_data = paginator.paginate_queryset(self.get_queryset(), self.request)
        serializer = FeedItemResponseSerializer(
            paginated_data,
            context={
                "user": self.request.user,
                "liked_news": get_liked_news(self.request.user, paginated_data),
            },
            many=True,
        )
        response = paginator.get_paginated_response(serializer.data)
        response.data["counts"] = self.get_category_counts()
        return response
