from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from rest_framework.generics import CreateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from feed.pagination import FeedPagination
from feed.services import get_liked_news

from news.models import News
from .serializers import NewsFeedListSerializer
from projects.models import Project
from vacancy.models import Vacancy


class NewSimpleFeed(APIView):
    serializator_class = NewsFeedListSerializer
    pagination_class = FeedPagination

    def _get_filter_data(self) -> list[str]:
        filter_queries: str | None = self.request.query_params.get("type")
        filter_queries: str = filter_queries if filter_queries else ""  # existence check

        news_types: list[str] = filter_queries.split("|")
        if "news" in news_types:
            news_types.append("customuser")
        return news_types

    def get_queryset(self) -> QuerySet[News]:
        filters = self._get_filter_data()
        queryset = (
            News.objects.select_related("content_type")
            .prefetch_related("content_object", "files")
            .filter(content_type__model__in=filters)
            .order_by("-datetime_created")
        )
        return queryset

    def get(self, *args, **kwargs):
        paginator = self.pagination_class()
        paginated_data = paginator.paginate_queryset(self.get_queryset(), self.request)
        serializer = NewsFeedListSerializer(
            paginated_data,
            context={
                "user": self.request.user,
                "liked_news": get_liked_news(self.request.user, paginated_data),
            },
            many=True,
        )

        new_data = []
        # временная подстройка данных под фронт
        for data in serializer.data:
            if data["type_model"] in ["project", "vacancy", None]:
                fomated_data = {
                    "type_model": data["type_model"],
                    "content": data["content_object"],
                }
            elif data["type_model"] == "news":
                del data["type_model"]
                fomated_data = {"type_model": "news", "content": data}
            new_data.append(fomated_data)

        return paginator.get_paginated_response(new_data)


class DevScript(CreateAPIView):
    def create(self, request):
        content_type_project = ContentType.objects.filter(model="project").first()
        for project in Project.objects.filter(draft=False):
            if not News.objects.filter(
                content_type=content_type_project, object_id=project.id
            ).exists():
                News.objects.create(
                    content_type=content_type_project,
                    object_id=project.id,
                    datetime_created=project.datetime_created,
                )

        content_type_vacancy = ContentType.objects.filter(model="vacancy").first()
        for vacancy in Vacancy.objects.filter(is_active=True):
            if not News.objects.filter(
                content_type=content_type_vacancy, object_id=vacancy.id
            ).exists():
                News.objects.create(
                    content_type=content_type_vacancy,
                    object_id=vacancy.id,
                    datetime_created=vacancy.datetime_created,
                )

        news_to_delete = list(
            News.objects.filter(
                content_type__in=[content_type_vacancy, content_type_project]
            )
        )

        for news in news_to_delete:
            if not news.content_object:
                news.delete()

        return Response({"status": "success"}, status=201)
