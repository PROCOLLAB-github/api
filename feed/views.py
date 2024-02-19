import random

from django.db.models import QuerySet
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from feed.constants import SupportedModel, model_mapping, SupportedQuerySet, FeedItemType
from feed.helpers import (
    collect_querysets,
    paginate_feed,
    add_pagination
)
from feed.pagination import FeedPagination


class FeedList(APIView):
    pagination_class = FeedPagination

    @swagger_auto_schema(
        responses={
            200: openapi.Response(
                description="List of some news: new projects, vacancies, project, users and program news",
                schema=openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        description="Feed item",
                        properties={
                            "type": openapi.TYPE_STRING,
                            "content": openapi.TYPE_OBJECT,
                        },
                    ),
                ),
            )
        }
    )
    def get(self, request: Request, *args, **kwargs) -> Response:
        models_to_get: list[SupportedModel] = self.get_request_data()
        full_queryset_data: dict[FeedItemType, SupportedQuerySet] = self.get_response_data(models_to_get)
        paginated_data, sum_pages = self.paginate_data(full_queryset_data)

        return Response(
            status=status.HTTP_200_OK, data=add_pagination(paginated_data, sum_pages)
        )

    def get_request_data(self) -> list[SupportedModel]:
        filter_queries = self.request.query_params.get("type")
        filter_queries = filter_queries if filter_queries else ''  # existence check

        models = [model_mapping[model_name] for model_name in model_mapping.keys() if model_name in filter_queries]
        return models

    def get_response_data(
            self, models: list[SupportedModel]
    ) -> dict[FeedItemType, SupportedQuerySet]:
        return {model.__name__: collect_querysets(model) for model in models}

    def paginate_data(self, get_model_data: dict[FeedItemType, SupportedQuerySet]) -> tuple[list[dict], int]:
        paginator = self.pagination_class()
        return paginate_feed(get_model_data, paginator, self.request, self)
