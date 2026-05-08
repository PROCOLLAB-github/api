from rest_framework.response import Response

from courses.api.response import serialize_response
from courses.api.serializers import LessonDetailSerializer
from courses.queries import build_lesson_detail_payload

from .base import AuthenticatedCourseAPIView


class LessonDetailAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        return Response(
            serialize_response(
                LessonDetailSerializer,
                build_lesson_detail_payload(request.user, pk),
            )
        )
