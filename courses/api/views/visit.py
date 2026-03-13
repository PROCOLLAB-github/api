from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework import status

from courses.api.serializers import CourseVisitResultSerializer, CourseVisitSerializer
from courses.services.access import resolve_course_availability
from courses.services.progress import touch_course_visit
from courses.services.querysets import published_course_queryset

from .base import AuthenticatedCourseAPIView


class CourseVisitAPIView(AuthenticatedCourseAPIView):

    def post(self, request, pk: int):
        serializer = CourseVisitSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        course = get_object_or_404(published_course_queryset(), pk=pk)
        availability = resolve_course_availability(course, request.user)
        if not availability.is_available:
            raise PermissionDenied("Курс пока недоступен.")
        progress = touch_course_visit(request.user, course)
        result_serializer = CourseVisitResultSerializer(
            {"last_visit_at": progress.last_visit_at}
        )
        return Response(result_serializer.data, status=status.HTTP_200_OK)
