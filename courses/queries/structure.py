from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from courses.models import (
    CourseModule,
    CourseModuleContentStatus,
    ProgressStatus,
    UserCourseProgress,
    UserLessonProgress,
    UserModuleProgress,
)
from courses.services.access import (
    is_lesson_available,
    is_module_available,
    resolve_course_availability,
)
from courses.services.progress import progress_payload
from courses.services.querysets import (
    published_course_queryset,
    published_lessons_prefetch,
)


def build_course_structure_payload(user, pk: int) -> dict:
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
            user=user,
            module_id__in=module_ids,
        )
    }
    lesson_progress_map = {
        progress.lesson_id: progress
        for progress in UserLessonProgress.objects.filter(
            user=user,
            lesson_id__in=lesson_ids,
        )
    }
    course_progress = UserCourseProgress.objects.filter(user=user, course=course).first()
    course_progress_data = progress_payload(course_progress)
    course_availability = resolve_course_availability(course, user)

    modules_payload = []
    previous_module_completed = True
    for module in modules:
        module_progress = module_progress_map.get(module.id)
        module_progress_data = progress_payload(module_progress)
        module_completed = module_progress_data["status"] == ProgressStatus.COMPLETED
        module_available = is_module_available(
            module,
            course_available=course_availability.is_available,
            previous_module_completed=previous_module_completed,
        )

        lessons_payload = []
        previous_lesson_completed = True
        for lesson in module.lessons.all():
            lesson_progress = lesson_progress_map.get(lesson.id)
            lesson_progress_data = progress_payload(lesson_progress)
            lesson_completed = (
                lesson_progress_data["status"] == ProgressStatus.COMPLETED
            )
            lesson_available = is_lesson_available(
                lesson,
                module_available=module_available,
                previous_lesson_completed=previous_lesson_completed,
            )
            lesson_status = lesson_progress_data["status"]
            lesson_percent = lesson_progress_data["percent"]
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
                "progress_status": module_progress_data["status"],
                "percent": module_progress_data["percent"],
                "lessons": lessons_payload,
            }
        )
        previous_module_completed = module_completed

    return {
        "course_id": course.id,
        "partner_program_id": course.partner_program_id,
        "progress_status": course_progress_data["status"],
        "percent": course_progress_data["percent"],
        "modules": modules_payload,
    }
