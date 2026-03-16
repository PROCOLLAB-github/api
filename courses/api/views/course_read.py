from rest_framework.response import Response

from courses.api.serializers import (
    CourseCardSerializer,
    CourseDetailSerializer,
    CourseStructureSerializer,
)
from courses.queries import (
    build_course_detail_payload,
    build_course_list_payload,
    build_course_structure_payload,
)

from .base import AuthenticatedCourseAPIView


class CourseListAPIView(AuthenticatedCourseAPIView):

    def get(self, request):
        serializer = CourseCardSerializer(
            data=build_course_list_payload(request.user),
            many=True,
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class CourseDetailAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        serializer = CourseDetailSerializer(
            data=build_course_detail_payload(request.user, pk)
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class CourseStructureAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        serializer = CourseStructureSerializer(
            data=build_course_structure_payload(request.user, pk)
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
