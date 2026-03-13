from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from courses.api.serializers import (
    TaskAnswerSubmitResultSerializer,
    TaskAnswerSubmitSerializer,
)
from courses.models import (
    CourseContentStatus,
    CourseLessonContentStatus,
    CourseModuleContentStatus,
    CourseTask,
    CourseTaskContentStatus,
)
from courses.services.answers import submit_user_task_answer
from courses.services.learning_flow import ensure_task_submission_access
from courses.services.progress import recalculate_user_progresses_for_lesson

from .base import AuthenticatedCourseAPIView


class CourseTaskAnswerSubmitAPIView(AuthenticatedCourseAPIView):

    def post(self, request, pk: int):
        task = get_object_or_404(
            CourseTask.objects.filter(
                status=CourseTaskContentStatus.PUBLISHED,
                lesson__status=CourseLessonContentStatus.PUBLISHED,
                lesson__module__status=CourseModuleContentStatus.PUBLISHED,
                lesson__module__course__status__in=(
                    CourseContentStatus.PUBLISHED,
                    CourseContentStatus.COMPLETED,
                ),
            )
            .select_related("lesson", "lesson__module", "lesson__module__course"),
            pk=pk,
        )
        ensure_task_submission_access(request.user, task)

        serializer = TaskAnswerSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            result = submit_user_task_answer(
                request.user,
                task,
                serializer.to_payload(),
            )
            recalculate_user_progresses_for_lesson(request.user, task.lesson)

        result_serializer = TaskAnswerSubmitResultSerializer(result)
        return Response(result_serializer.data, status=status.HTTP_200_OK)
