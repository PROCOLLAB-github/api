import io
from collections import defaultdict
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.db.models import Prefetch
from openpyxl import Workbook

from core.utils import build_xlsx_download_response, sanitize_excel_value
from courses.models import (
    Course,
    CourseLessonContentStatus,
    CourseModuleContentStatus,
    CourseTask,
    CourseTaskContentStatus,
    CourseTaskKind,
    ProgressStatus,
    UserCourseProgress,
    UserLessonProgress,
    UserTaskAnswer,
    UserTaskAnswerFile,
    UserTaskAnswerOption,
)


MSK_TZ = ZoneInfo("Europe/Moscow")
BASE_HEADERS = (
    "Имя и Фамилия",
    "Email",
    "Прогресс курса, %",
    "Дата начала прохождения",
    "Название курса",
    "Текущий этап",
)


def _format_msk_datetime(value) -> str:
    if value is None:
        return ""
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")


def _full_name(user) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()
    return full_name or user.email


def _export_tasks(course: Course) -> list[CourseTask]:
    return list(
        CourseTask.objects.filter(
            lesson__module__course=course,
            lesson__module__status=CourseModuleContentStatus.PUBLISHED,
            lesson__status=CourseLessonContentStatus.PUBLISHED,
            status=CourseTaskContentStatus.PUBLISHED,
            task_kind=CourseTaskKind.QUESTION,
        )
        .select_related("lesson__module")
        .order_by(
            "lesson__module__order",
            "lesson__module__id",
            "lesson__order",
            "lesson__id",
            "order",
            "id",
        )
    )


def _started_course_progresses(course: Course) -> list[UserCourseProgress]:
    return list(
        UserCourseProgress.objects.filter(
            course=course,
            started_at__isnull=False,
        )
        .select_related("user", "course")
        .order_by("user__last_name", "user__first_name", "user__email", "id")
    )


def _lesson_progresses_by_user(user_ids: list[int], course: Course) -> dict[int, list[UserLessonProgress]]:
    if not user_ids:
        return {}

    progress_map: dict[int, list[UserLessonProgress]] = defaultdict(list)
    progresses = (
        UserLessonProgress.objects.filter(
            user_id__in=user_ids,
            lesson__module__course=course,
            lesson__module__status=CourseModuleContentStatus.PUBLISHED,
            lesson__status=CourseLessonContentStatus.PUBLISHED,
        )
        .select_related("lesson__module", "current_task")
        .order_by(
            "lesson__module__order",
            "lesson__module__id",
            "lesson__order",
            "lesson__id",
            "id",
        )
    )
    for progress in progresses:
        progress_map[progress.user_id].append(progress)
    return progress_map


def _answers_by_user_and_task(
    user_ids: list[int],
    task_ids: list[int],
) -> dict[tuple[int, int], UserTaskAnswer]:
    if not user_ids or not task_ids:
        return {}

    answers = (
        UserTaskAnswer.objects.filter(user_id__in=user_ids, task_id__in=task_ids)
        .prefetch_related(
            Prefetch(
                "selected_options",
                queryset=UserTaskAnswerOption.objects.select_related("option").order_by(
                    "option__order",
                    "option__id",
                    "id",
                ),
            ),
            Prefetch(
                "files",
                queryset=UserTaskAnswerFile.objects.select_related("file").order_by(
                    "datetime_uploaded",
                    "id",
                ),
            ),
        )
    )
    return {(answer.user_id, answer.task_id): answer for answer in answers}


def _task_header(task: CourseTask) -> str:
    return (
        f"Модуль {task.lesson.module.order}: {task.lesson.module.title} / "
        f"Урок {task.lesson.order}: {task.lesson.title} / "
        f"Задание {task.order}: {task.title}"
    )


def _format_stage(
    course_progress: UserCourseProgress,
    lesson_progresses: list[UserLessonProgress],
) -> str:
    if course_progress.status == ProgressStatus.COMPLETED:
        return "Курс завершён"

    current_progress = next(
        (progress for progress in lesson_progresses if progress.current_task_id),
        None,
    )
    if current_progress is not None:
        current_task = current_progress.current_task
        return (
            f"Модуль {current_progress.lesson.module.order}: {current_progress.lesson.module.title} / "
            f"Урок {current_progress.lesson.order}: {current_progress.lesson.title} / "
            f"Задание {current_task.order}: {current_task.title}"
        )

    in_progress_lesson = next(
        (progress for progress in lesson_progresses if progress.status == ProgressStatus.IN_PROGRESS),
        None,
    )
    if in_progress_lesson is not None:
        return (
            f"Модуль {in_progress_lesson.lesson.module.order}: {in_progress_lesson.lesson.module.title} / "
            f"Урок {in_progress_lesson.lesson.order}: {in_progress_lesson.lesson.title}"
        )

    return "Этап не определён"


def _format_answer_cell(answer: UserTaskAnswer | None) -> str:
    if answer is None:
        return ""

    parts: list[str] = []
    if answer.answer_text:
        parts.append(answer.answer_text.strip())

    selected_options = [
        selected.option.text.strip()
        for selected in answer.selected_options.all()
        if selected.option.text.strip()
    ]
    if selected_options:
        parts.append("\n".join(selected_options))

    file_links = [attachment.file.link for attachment in answer.files.all()]
    if file_links:
        parts.append("\n".join(file_links))

    return "\n".join(part for part in parts if part)


def _build_headers(tasks: list[CourseTask]) -> list[str]:
    return [*BASE_HEADERS, *[_task_header(task) for task in tasks]]


def build_course_results_workbook_bytes(course: Course) -> bytes:
    tasks = _export_tasks(course)
    course_progresses = _started_course_progresses(course)
    user_ids = [progress.user_id for progress in course_progresses]
    task_ids = [task.id for task in tasks]

    lesson_progress_map = _lesson_progresses_by_user(user_ids, course)
    answers_map = _answers_by_user_and_task(user_ids, task_ids)

    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet(title="Результаты курса")
    worksheet.append([sanitize_excel_value(value) for value in _build_headers(tasks)])

    for course_progress in course_progresses:
        lesson_progresses = lesson_progress_map.get(course_progress.user_id, [])
        row = [
            _full_name(course_progress.user),
            course_progress.user.email,
            course_progress.percent,
            _format_msk_datetime(course_progress.started_at),
            course.title,
            _format_stage(course_progress, lesson_progresses),
        ]
        for task in tasks:
            row.append(
                _format_answer_cell(
                    answers_map.get((course_progress.user_id, task.id))
                )
            )
        worksheet.append([sanitize_excel_value(value) for value in row])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def build_course_results_export_response(course: Course):
    binary_data = build_course_results_workbook_bytes(course)

    date_suffix = timezone.now().astimezone(MSK_TZ).strftime("%d.%m.%Y")
    base_name = f"course-results - {course.title} - {date_suffix}"
    return build_xlsx_download_response(binary_data, base_name=base_name)
