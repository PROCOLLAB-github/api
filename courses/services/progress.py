from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from courses.models import (
    Course,
    CourseLesson,
    CourseModule,
    ProgressStatus,
    UserCourseProgress,
    UserLessonProgress,
    UserModuleProgress,
)


@dataclass(slots=True, frozen=True)
class ProgressSnapshot:
    status: str
    percent: int


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
