from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from feed.helpers import get_n_random_projects, get_n_latest_created_projects
from projects.serializers import ProjectListSerializer


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
                    ),
                ),
            )
        }
    )
    def get(self, request: Request, *args, **kwargs) -> Response:
        return Response(status=status.HTTP_200_OK, data=collect_feed())


def collect_feed() -> list:
    n_random_projects = get_n_random_projects(3)
    n_latest_created_projects = get_n_latest_created_projects(3)
    serializer = ProjectListSerializer(
        data=set(n_random_projects + n_latest_created_projects), many=True
    )

    serializer.is_valid()
    return serializer.data
