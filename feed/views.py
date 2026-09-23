from django.db.models import Count, Q, QuerySet
from rest_framework.views import APIView

from feed.pagination import FeedPagination
from feed.services import get_liked_news
from news.models import News
from projects.models import Project
from vacancy.models import Vacancy

from .serializers import FeedItemResponseSerializer


class NewSimpleFeed(APIView):
    serializer_class = FeedItemResponseSerializer
    pagination_class = FeedPagination

    def _get_filter_data(self) -> list[str]:
        filter_queries: str | None = self.request.query_params.get("type")
        filter_queries: str = filter_queries if filter_queries else ""  # existence check

        news_types: list[str] = filter_queries.split("|")
        if "news" in news_types:
            news_types.append("customuser")
        return [news_type for news_type in news_types if news_type != "partnerprogram"]

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
        return (
            self.get_visible_queryset()
            .filter(content_type__model__in=self._get_filter_data())
            .order_by("-datetime_created", "-pk")
        )

    def get_category_counts(self) -> dict[str, int]:
        # Программы и образование пока не включены в ленту; не считаем скрытый контент.
        counts = self.get_visible_queryset().aggregate(
            project=Count("pk", filter=Q(content_type__model="project")),
            vacancy=Count("pk", filter=Q(content_type__model="vacancy")),
            news=Count("pk", filter=Q(content_type__model="customuser")),
        )
        return {
            "all": sum(counts.values()),
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
