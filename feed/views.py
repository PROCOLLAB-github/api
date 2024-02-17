from typing import List, Tuple, Dict

import random

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from feed.constants import SupportedModel
from feed.helpers import (
    add_pagination,
    collect_querysets,
    paginate_model_items,
    to_feed_items,
)
from news.models import News
from projects.models import Project
from vacancy.models import Vacancy


class FeedList(APIView):
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
        models_to_get, page_number = self.get_request_data()
        queryset_ready, total_pages = self.get_queryset(models_to_get, page_number)
        return Response(
            status=status.HTTP_200_OK, data=add_pagination(queryset_ready, total_pages)
        )

    def get_request_data(self) -> Tuple[List[SupportedModel], int]:
        models = []
        page_number = int(self.request.query_params.get("page_number"))

        if not (filter_queries := self.request.query_params.get("type")):
            return [], 0
        if "news" in filter_queries:
            models.append(News)
        if "project" in filter_queries:
            models.append(Project)
        if "vacancy" in filter_queries:
            models.append(Vacancy)

        return models, page_number

    def get_queryset(
        self, models: List[SupportedModel], page_number: int
    ) -> Tuple[List[Dict], int]:
        get_model_data = {model.__name__: collect_querysets(model) for model in models}
        result = []
        sum_num_pages = 0
        for model in get_model_data:
            get_model_data[model], num_pages = paginate_model_items(
                get_model_data[model], page_number
            )
            sum_num_pages += num_pages
            result.extend(to_feed_items(model, get_model_data[model]))
        random.shuffle(result)
        return result, sum_num_pages
