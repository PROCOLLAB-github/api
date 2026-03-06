from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from courses.models import (
    Course,
    CourseAccessType,
    CourseContentStatus,
    CourseLesson,
    CourseLessonContentStatus,
    CourseModule,
    CourseModuleContentStatus,
    ProgressStatus,
    UserCourseProgress,
)

MSK_TZ = ZoneInfo("Europe/Moscow")

ACTION_START = "start"
ACTION_CONTINUE = "continue"
ACTION_LOCK = "lock"


@dataclass(slots=True, frozen=True)
class CourseAvailability:
    is_available: bool
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class CourseCardState:
    is_available: bool
    action_state: str
    date_label: str


def moscow_today(moment: datetime | None = None) -> date:
    if moment is None:
        moment = timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.get_current_timezone())
    return moment.astimezone(MSK_TZ).date()


def is_course_completed(course: Course, *, today: date | None = None) -> bool:
    current_day = today or moscow_today()
    if course.status == CourseContentStatus.COMPLETED or course.is_completed:
        return True
    return bool(course.end_date and current_day > course.end_date)


def is_user_program_member(course: Course, user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if not course.partner_program_id:
        return False
    return course.partner_program.users.filter(pk=user.pk).exists()


def resolve_course_availability(
    course: Course,
    user,
    *,
    today: date | None = None,
) -> CourseAvailability:
    if not getattr(user, "is_authenticated", False):
        return CourseAvailability(is_available=False, reason="authentication_required")

    if course.status == CourseContentStatus.DRAFT:
        return CourseAvailability(is_available=False, reason="draft")

    if is_course_completed(course, today=today):
        return CourseAvailability(is_available=False, reason="completed")

    if course.access_type == CourseAccessType.SUBSCRIPTION_STUB:
        return CourseAvailability(is_available=False, reason="subscription_required")

    if course.access_type == CourseAccessType.PROGRAM_MEMBERS:
        if not course.partner_program_id:
            return CourseAvailability(is_available=False, reason="program_not_set")
        if not is_user_program_member(course, user):
            return CourseAvailability(is_available=False, reason="not_program_member")

    return CourseAvailability(is_available=True)


def resolve_course_action_state(
    course: Course,
    user,
    *,
    progress: UserCourseProgress | None = None,
    today: date | None = None,
    availability: CourseAvailability | None = None,
) -> str:
    resolved_availability = availability or resolve_course_availability(
        course, user, today=today
    )
    if not resolved_availability.is_available:
        return ACTION_LOCK

    if progress is None or progress.status == ProgressStatus.NOT_STARTED:
        return ACTION_START
    if progress.status == ProgressStatus.IN_PROGRESS:
        return ACTION_CONTINUE
    return ACTION_LOCK


def resolve_course_date_label(course: Course, *, today: date | None = None) -> str:
    current_day = today or moscow_today()

    if is_course_completed(course, today=current_day):
        return "курс завершен"

    if not course.start_date and not course.end_date:
        return "бессрочно"

    if course.start_date and course.end_date:
        if current_day < course.start_date:
            return f"{course.start_date:%d.%m.%y} - {course.end_date:%d.%m.%y}"
        return f"доступен до {course.end_date:%d.%m.%Y}"

    return ""


def resolve_course_card_state(
    course: Course,
    user,
    *,
    progress: UserCourseProgress | None = None,
    today: date | None = None,
) -> CourseCardState:
    availability = resolve_course_availability(course, user, today=today)
    action_state = resolve_course_action_state(
        course,
        user,
        progress=progress,
        today=today,
        availability=availability,
    )
    date_label = resolve_course_date_label(course, today=today)
    return CourseCardState(
        is_available=availability.is_available,
        action_state=action_state,
        date_label=date_label,
    )


def is_module_available(
    module: CourseModule,
    *,
    course_available: bool,
    previous_module_completed: bool,
    today: date | None = None,
) -> bool:
    current_day = today or moscow_today()
    if not course_available:
        return False
    if module.status != CourseModuleContentStatus.PUBLISHED:
        return False
    if module.start_date and current_day < module.start_date:
        return False
    if not previous_module_completed:
        return False
    return True


def is_lesson_available(
    lesson: CourseLesson,
    *,
    module_available: bool,
    previous_lesson_completed: bool,
) -> bool:
    if not module_available:
        return False
    if lesson.status != CourseLessonContentStatus.PUBLISHED:
        return False
    if not previous_lesson_completed:
        return False
    return True
