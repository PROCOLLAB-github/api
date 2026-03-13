from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from courses.models import (
    Course,
    CourseLesson,
    CourseLessonContentStatus,
    CourseModule,
    CourseModuleContentStatus,
    CourseTaskContentStatus,
    ProgressStatus,
    UserCourseProgress,
    UserLessonProgress,
    UserModuleProgress,
)


@dataclass(slots=True, frozen=True)
class ProgressSnapshot:
    status: str
    percent: int


def not_started_progress_payload() -> dict:
    return {"status": ProgressStatus.NOT_STARTED, "percent": 0}


def progress_payload(progress) -> dict:
    if progress is None:
        return not_started_progress_payload()
    return {
        "status": progress.status,
        "percent": progress.percent,
    }


def percent_from_counts(completed_count: int, total_count: int) -> int:
    if total_count <= 0:
        return 0
    if completed_count <= 0:
        return 0
    if completed_count >= total_count:
        return 100
    return int((completed_count * 100) / total_count)


def percent_from_total_percent(total_percent: int, total_count: int) -> int:
    if total_count <= 0:
        return 0
    if total_percent <= 0:
        return 0

    normalized_percent = int(total_percent / total_count)
    if normalized_percent <= 0:
        return 0
    if normalized_percent >= 100:
        return 100
    return normalized_percent


def status_from_percent(
    percent: int,
    *,
    allow_blocked: bool = False,
    blocked: bool = False,
) -> str:
    if blocked and allow_blocked:
        return ProgressStatus.BLOCKED
    if percent <= 0:
        return ProgressStatus.NOT_STARTED
    if percent >= 100:
        return ProgressStatus.COMPLETED
    return ProgressStatus.IN_PROGRESS


def build_progress_snapshot(
    completed_count: int,
    total_count: int,
    *,
    allow_blocked: bool = False,
    blocked: bool = False,
) -> ProgressSnapshot:
    percent = percent_from_counts(completed_count, total_count)
    status = status_from_percent(percent, allow_blocked=allow_blocked, blocked=blocked)
    return ProgressSnapshot(status=status, percent=percent)


def build_progress_snapshot_from_percent(
    percent: int,
    *,
    allow_blocked: bool = False,
    blocked: bool = False,
) -> ProgressSnapshot:
    normalized_percent = max(0, min(100, int(percent)))
    status = status_from_percent(
        normalized_percent,
        allow_blocked=allow_blocked,
        blocked=blocked,
    )
    return ProgressSnapshot(status=status, percent=normalized_percent)


def upsert_course_progress(
    user,
    course: Course,
    *,
    percent: int,
    touch_visit: bool = False,
    visited_at: datetime | None = None,
) -> UserCourseProgress:
    snapshot = build_progress_snapshot_from_percent(percent)
    manager = UserCourseProgress.objects
    if transaction.get_connection().in_atomic_block:
        manager = manager.select_for_update()
    progress = manager.filter(user=user, course=course).first()
    if progress is None:
        progress = UserCourseProgress(user=user, course=course)

    progress.status = snapshot.status
    progress.percent = snapshot.percent
    if touch_visit:
        progress.last_visit_at = visited_at or timezone.now()
    try:
        progress.save(validate=False)
    except IntegrityError:
        # Concurrent create: retry as locked update.
        retry_manager = UserCourseProgress.objects
        if transaction.get_connection().in_atomic_block:
            retry_manager = retry_manager.select_for_update()
        progress = retry_manager.get(user=user, course=course)
        progress.status = snapshot.status
        progress.percent = snapshot.percent
        if touch_visit:
            progress.last_visit_at = visited_at or timezone.now()
        progress.save(validate=False)
    return progress


def upsert_module_progress(
    user,
    module: CourseModule,
    *,
    percent: int,
) -> UserModuleProgress:
    snapshot = build_progress_snapshot_from_percent(percent)
    manager = UserModuleProgress.objects
    if transaction.get_connection().in_atomic_block:
        manager = manager.select_for_update()
    progress = manager.filter(user=user, module=module).first()
    if progress is None:
        progress = UserModuleProgress(user=user, module=module)

    progress.status = snapshot.status
    progress.percent = snapshot.percent
    try:
        progress.save(validate=False)
    except IntegrityError:
        retry_manager = UserModuleProgress.objects
        if transaction.get_connection().in_atomic_block:
            retry_manager = retry_manager.select_for_update()
        progress = retry_manager.get(user=user, module=module)
        progress.status = snapshot.status
        progress.percent = snapshot.percent
        progress.save(validate=False)
    return progress


def upsert_lesson_progress(
    user,
    lesson: CourseLesson,
    *,
    completed_tasks: int,
    total_tasks: int,
    current_task=None,
    blocked: bool = False,
) -> UserLessonProgress:
    snapshot = build_progress_snapshot(
        completed_tasks,
        total_tasks,
        allow_blocked=True,
        blocked=blocked,
    )
    manager = UserLessonProgress.objects
    if transaction.get_connection().in_atomic_block:
        manager = manager.select_for_update()
    progress = manager.filter(user=user, lesson=lesson).first()
    if progress is None:
        progress = UserLessonProgress(user=user, lesson=lesson)

    progress.status = snapshot.status
    progress.percent = snapshot.percent
    progress.current_task = current_task
    try:
        progress.save(validate=False)
    except IntegrityError:
        retry_manager = UserLessonProgress.objects
        if transaction.get_connection().in_atomic_block:
            retry_manager = retry_manager.select_for_update()
        progress = retry_manager.get(user=user, lesson=lesson)
        progress.status = snapshot.status
        progress.percent = snapshot.percent
        progress.current_task = current_task
        progress.save(validate=False)
    return progress


@transaction.atomic
def touch_course_visit(
    user,
    course: Course,
    *,
    visited_at: datetime | None = None,
) -> UserCourseProgress:
    progress = UserCourseProgress.objects.select_for_update().filter(
        user=user,
        course=course,
    ).first()
    if progress is None:
        progress = UserCourseProgress(user=user, course=course)
    progress.last_visit_at = visited_at or timezone.now()
    try:
        progress.save(validate=False)
    except IntegrityError:
        progress = UserCourseProgress.objects.select_for_update().get(
            user=user,
            course=course,
        )
        progress.last_visit_at = visited_at or timezone.now()
        progress.save(validate=False)
    return progress


def recalculate_user_progresses_for_lesson(user, lesson: CourseLesson) -> None:
    from courses.services.learning_flow import (
        answers_by_task,
        first_unfinished_task,
        task_completion_map_from_answers,
    )

    module = lesson.module
    course = module.course

    lesson_tasks = list(
        lesson.tasks.filter(status=CourseTaskContentStatus.PUBLISHED).order_by(
            "order",
            "id",
        )
    )
    lesson_answer_map = answers_by_task(user, lesson_tasks)
    lesson_completion_map = task_completion_map_from_answers(
        lesson_tasks,
        lesson_answer_map,
    )
    lesson_total_tasks = len(lesson_tasks)
    lesson_completed_tasks = sum(
        1 for task in lesson_tasks if lesson_completion_map.get(task.id, False)
    )
    current_task = first_unfinished_task(lesson_tasks, lesson_completion_map)
    upsert_lesson_progress(
        user,
        lesson,
        completed_tasks=lesson_completed_tasks,
        total_tasks=lesson_total_tasks,
        current_task=current_task,
    )

    module_total_lessons = module.lessons.filter(
        status=CourseLessonContentStatus.PUBLISHED
    ).count()
    module_percent_total = (
        UserLessonProgress.objects.filter(
            user=user,
            lesson__module=module,
            lesson__status=CourseLessonContentStatus.PUBLISHED,
        ).aggregate(total=Sum("percent"))["total"]
        or 0
    )
    upsert_module_progress(
        user=user,
        module=module,
        percent=percent_from_total_percent(module_percent_total, module_total_lessons),
    )

    course_total_lessons = CourseLesson.objects.filter(
        module__course=course,
        module__status=CourseModuleContentStatus.PUBLISHED,
        status=CourseLessonContentStatus.PUBLISHED,
    ).count()
    course_percent_total = (
        UserLessonProgress.objects.filter(
            user=user,
            lesson__module__course=course,
            lesson__module__status=CourseModuleContentStatus.PUBLISHED,
            lesson__status=CourseLessonContentStatus.PUBLISHED,
        ).aggregate(total=Sum("percent"))["total"]
        or 0
    )
    upsert_course_progress(
        user=user,
        course=course,
        percent=percent_from_total_percent(course_percent_total, course_total_lessons),
    )
