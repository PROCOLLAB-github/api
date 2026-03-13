from rest_framework.response import Response

from courses.api.serializers import LessonDetailSerializer
from courses.queries import build_lesson_detail_payload

from .base import AuthenticatedCourseAPIView


class LessonDetailAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        serializer = LessonDetailSerializer(
            data=build_lesson_detail_payload(request.user, pk)
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
