from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from courses.models import (
    CourseContentStatus,
    CourseLesson,
    CourseLessonContentStatus,
    CourseModuleContentStatus,
    CourseTask,
    CourseTaskAnswerType,
    CourseTaskContentStatus,
    CourseTaskOption,
)
from courses.services.learning_flow import (
    ensure_lesson_access,
    first_unfinished_task,
    task_completion_map,
)
from courses.services.progress import build_progress_snapshot


def build_lesson_detail_payload(user, pk: int) -> dict:
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

    ensure_lesson_access(user, lesson)
    tasks = list(lesson.tasks.all())
    completion_map = task_completion_map(user, tasks)
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

    return {
        "id": lesson.id,
        "module_id": lesson.module_id,
        "course_id": lesson.module.course_id,
        "title": lesson.title,
        "progress_status": snapshot.status,
        "percent": snapshot.percent,
        "current_task_id": current_task_id,
        "tasks": tasks_payload,
    }
