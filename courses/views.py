from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from courses.models import (
    CourseContentStatus,
    CourseLesson,
    CourseLessonContentStatus,
    CourseModule,
    CourseModuleContentStatus,
    CourseTask,
    CourseTaskAnswerType,
    CourseTaskContentStatus,
    CourseTaskKind,
    CourseTaskOption,
    ProgressStatus,
    UserCourseProgress,
    UserLessonProgress,
    UserModuleProgress,
)
from courses.serializers import (
    CourseCardSerializer,
    CourseDetailSerializer,
    CourseStructureSerializer,
    CourseVisitResultSerializer,
    CourseVisitSerializer,
    LessonDetailSerializer,
    TaskAnswerSubmitResultSerializer,
    TaskAnswerSubmitSerializer,
)
from courses.services.access import (
    is_lesson_available,
    is_module_available,
    resolve_course_availability,
    resolve_course_card_state,
)
from courses.services.answers import submit_user_task_answer
from courses.services.learning_flow import (
    ensure_lesson_access,
    ensure_task_submission_access,
    first_unfinished_task,
    progress_payload,
    recalculate_user_progresses_for_lesson,
    task_completion_map,
)
from courses.services.progress import build_progress_snapshot, touch_course_visit
from courses.services.querysets import (
    published_course_queryset,
    published_lessons_prefetch,
)


class AuthenticatedCourseAPIView(APIView):
    permission_classes = [IsAuthenticated]


class CourseListAPIView(AuthenticatedCourseAPIView):

    def get(self, request):
        courses = list(
            published_course_queryset()
            .select_related("partner_program", "avatar_file", "card_cover_file")
            .order_by("-datetime_created")
        )
        progress_map = {
            progress.course_id: progress
            for progress in UserCourseProgress.objects.filter(
                user=request.user,
                course_id__in=[course.id for course in courses],
            )
        }

        data = []
        for course in courses:
            progress = progress_map.get(course.id)
            card_state = resolve_course_card_state(course, request.user, progress=progress)
            normalized_progress = progress_payload(progress)
            data.append(
                {
                    "id": course.id,
                    "partner_program_id": course.partner_program_id,
                    "title": course.title,
                    "access_type": course.access_type,
                    "status": course.status,
                    "avatar_url": course.avatar_file_id,
                    "card_cover_url": course.card_cover_file_id,
                    "start_date": course.start_date,
                    "end_date": course.end_date,
                    "date_label": card_state.date_label,
                    "is_available": card_state.is_available,
                    "action_state": card_state.action_state,
                    "progress_status": normalized_progress["status"],
                    "percent": normalized_progress["percent"],
                }
            )

        serializer = CourseCardSerializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class CourseDetailAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        course = get_object_or_404(
            published_course_queryset().select_related(
                "partner_program",
                "avatar_file",
                "header_cover_file",
            ),
            pk=pk,
        )
        progress = (
            UserCourseProgress.objects.filter(user=request.user, course=course).first()
        )
        normalized_progress = progress_payload(progress)
        card_state = resolve_course_card_state(course, request.user, progress=progress)

        serializer = CourseDetailSerializer(
            data={
                "id": course.id,
                "partner_program_id": course.partner_program_id,
                "title": course.title,
                "description": course.description,
                "access_type": course.access_type,
                "status": course.status,
                "avatar_url": course.avatar_file_id,
                "header_cover_url": course.header_cover_file_id,
                "start_date": course.start_date,
                "end_date": course.end_date,
                "date_label": card_state.date_label,
                "is_available": card_state.is_available,
                "progress_status": normalized_progress["status"],
                "percent": normalized_progress["percent"],
                "analytics_stub": {
                    "enabled": False,
                    "title": "Аналитика",
                    "state": "coming_soon",
                    "text": "пока закрыто",
                },
            }
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class CourseStructureAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        course = get_object_or_404(
            published_course_queryset().prefetch_related(
                Prefetch(
                    "modules",
                    queryset=CourseModule.objects.filter(
                        status=CourseModuleContentStatus.PUBLISHED
                    )
                    .select_related("avatar_file")
                    .order_by("order", "id")
                    .prefetch_related(published_lessons_prefetch()),
                ),
            ),
            pk=pk,
        )
        modules = list(course.modules.all())
        module_ids = [module.id for module in modules]
        lessons = [lesson for module in modules for lesson in module.lessons.all()]
        lesson_ids = [lesson.id for lesson in lessons]

        module_progress_map = {
            progress.module_id: progress
            for progress in UserModuleProgress.objects.filter(
                user=request.user, module_id__in=module_ids
            )
        }
        lesson_progress_map = {
            progress.lesson_id: progress
            for progress in UserLessonProgress.objects.filter(
                user=request.user, lesson_id__in=lesson_ids
            )
        }
        course_progress = (
            UserCourseProgress.objects.filter(user=request.user, course=course).first()
        )
        course_progress_payload = progress_payload(course_progress)
        course_availability = resolve_course_availability(course, request.user)

        modules_payload = []
        previous_module_completed = True
        for module in modules:
            module_progress = module_progress_map.get(module.id)
            module_progress_payload = progress_payload(module_progress)
            module_completed = module_progress_payload["status"] == ProgressStatus.COMPLETED
            module_available = is_module_available(
                module,
                course_available=course_availability.is_available,
                previous_module_completed=previous_module_completed,
            )

            lessons_payload = []
            previous_lesson_completed = True
            for lesson in module.lessons.all():
                lesson_progress = lesson_progress_map.get(lesson.id)
                lesson_progress_payload = progress_payload(lesson_progress)
                lesson_completed = (
                    lesson_progress_payload["status"] == ProgressStatus.COMPLETED
                )
                lesson_available = is_lesson_available(
                    lesson,
                    module_available=module_available,
                    previous_lesson_completed=previous_lesson_completed,
                )
                lesson_status = lesson_progress_payload["status"]
                lesson_percent = lesson_progress_payload["percent"]
                if not lesson_available and lesson_status != ProgressStatus.COMPLETED:
                    lesson_status = ProgressStatus.BLOCKED
                    lesson_percent = 0

                lessons_payload.append(
                    {
                        "id": lesson.id,
                        "module_id": module.id,
                        "title": lesson.title,
                        "order": lesson.order,
                        "task_count": lesson.task_count,
                        "status": lesson.status,
                        "is_available": lesson_available,
                        "progress_status": lesson_status,
                        "percent": lesson_percent,
                        "current_task_id": (
                            lesson_progress.current_task_id if lesson_progress else None
                        ),
                    }
                )
                previous_lesson_completed = lesson_completed

            modules_payload.append(
                {
                    "id": module.id,
                    "course_id": course.id,
                    "title": module.title,
                    "order": module.order,
                    "avatar_url": module.avatar_file_id,
                    "start_date": module.start_date,
                    "status": module.status,
                    "is_available": module_available,
                    "progress_status": module_progress_payload["status"],
                    "percent": module_progress_payload["percent"],
                    "lessons": lessons_payload,
                }
            )
            previous_module_completed = module_completed

        serializer = CourseStructureSerializer(
            data={
                "course_id": course.id,
                "partner_program_id": course.partner_program_id,
                "progress_status": course_progress_payload["status"],
                "percent": course_progress_payload["percent"],
                "modules": modules_payload,
            }
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class LessonDetailAPIView(AuthenticatedCourseAPIView):

    def get(self, request, pk: int):
        lesson = get_object_or_404(
            CourseLesson.objects.filter(
                status=CourseLessonContentStatus.PUBLISHED,
                module__status=CourseModuleContentStatus.PUBLISHED,
                module__course__status__in=(
                    CourseContentStatus.PUBLISHED,
                    CourseContentStatus.COMPLETED,
                ),
            )
            .select_related("module", "module__course")
            .prefetch_related(
                Prefetch(
                    "tasks",
                    queryset=CourseTask.objects.filter(
                        status=CourseTaskContentStatus.PUBLISHED
                    )
                    .order_by("order", "id")
                    .prefetch_related(
                        Prefetch(
                            "options",
                            queryset=CourseTaskOption.objects.order_by("order", "id"),
                        )
                    ),
                ),
            ),
            pk=pk,
        )

        ensure_lesson_access(request.user, lesson)
        tasks = list(lesson.tasks.all())
        completion_map = task_completion_map(request.user, tasks)
        current_task = first_unfinished_task(tasks, completion_map)
        total_tasks = len(tasks)
        completed_tasks = sum(1 for task in tasks if completion_map.get(task.id, False))
        snapshot = build_progress_snapshot(completed_tasks, total_tasks)
        current_task_id = current_task.id if current_task is not None else None

        tasks_payload = []
        for task in tasks:
            is_completed = completion_map.get(task.id, False)
            is_available = is_completed or (
                current_task_id is not None and task.id == current_task_id
            )
            if current_task_id is None:
                is_available = True

            options_payload = []
            if task.answer_type in (
                CourseTaskAnswerType.SINGLE_CHOICE,
                CourseTaskAnswerType.MULTIPLE_CHOICE,
            ):
                options_payload = [
                    {"id": option.id, "order": option.order, "text": option.text}
                    for option in task.options.all()
                ]

            tasks_payload.append(
                {
                    "id": task.id,
                    "order": task.order,
                    "title": task.title,
                    "status": task.status,
                    "task_kind": task.task_kind,
                    "check_type": task.check_type,
                    "informational_type": task.informational_type,
                    "question_type": task.question_type,
                    "answer_type": task.answer_type,
                    "body_text": task.body_text,
                    "video_url": task.video_url,
                    "image_url": task.image_file_id,
                    "attachment_url": task.attachment_file_id,
                    "is_available": is_available,
                    "is_completed": is_completed,
                    "options": options_payload,
                }
            )

        serializer = LessonDetailSerializer(
            data={
                "id": lesson.id,
                "module_id": lesson.module_id,
                "course_id": lesson.module.course_id,
                "title": lesson.title,
                "progress_status": snapshot.status,
                "percent": snapshot.percent,
                "current_task_id": current_task_id,
                "tasks": tasks_payload,
            }
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class CourseTaskAnswerSubmitAPIView(AuthenticatedCourseAPIView):

    def post(self, request, pk: int):
        task = get_object_or_404(
            CourseTask.objects.filter(
                status=CourseTaskContentStatus.PUBLISHED,
                task_kind=CourseTaskKind.QUESTION,
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


class CourseVisitAPIView(AuthenticatedCourseAPIView):

    def post(self, request, pk: int):
        serializer = CourseVisitSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        course = get_object_or_404(published_course_queryset(), pk=pk)
        progress = touch_course_visit(request.user, course)
        result_serializer = CourseVisitResultSerializer(
            {"last_visit_at": progress.last_visit_at}
        )
        return Response(result_serializer.data, status=status.HTTP_200_OK)
