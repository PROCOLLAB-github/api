from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from feed.helpers import collect_feed
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
        models = []
        if request.query_params.get("news") != "false":
            models.append(News)
        if request.query_params.get("vacancies") != "false":
            models.append(Vacancy)
        if request.query_params.get("projects") != "false":
            models.append(Project)

        return Response(status=status.HTTP_200_OK, data=collect_feed(models, 3))
