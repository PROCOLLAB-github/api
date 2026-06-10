from rest_framework.response import Response

from courses.api.serializers import (
    CourseCardSerializer,
    CourseDetailSerializer,
    CourseStructureSerializer,
)
from courses.api.response import serialize_response
from courses.queries import (
    build_course_detail_payload,
    build_course_list_payload,
    build_course_structure_payload,
)

from .base import AuthenticatedCourseAPIView


class CourseListAPIView(AuthenticatedCourseAPIView):

    def get(self, request):
        return Response(
            serialize_response(
                CourseCardSerializer,
                build_course_list_payload(request.user),
                many=True,
            )
        )


class CourseDetailAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        return Response(
            serialize_response(
                CourseDetailSerializer,
                build_course_detail_payload(request.user, pk),
            )
        )


class CourseStructureAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        return Response(
            serialize_response(
                CourseStructureSerializer,
                build_course_structure_payload(request.user, pk),
            )
        )
