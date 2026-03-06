from rest_framework.exceptions import PermissionDenied

from courses.models import (
    CourseLesson,
    CourseLessonContentStatus,
    CourseModuleContentStatus,
    CourseTask,
    CourseTaskCheckType,
    CourseTaskContentStatus,
    CourseTaskKind,
    ProgressStatus,
    UserLessonProgress,
    UserModuleProgress,
    UserTaskAnswer,
    UserTaskAnswerStatus,
)
from courses.services.access import (
    is_lesson_available,
    is_module_available,
    resolve_course_availability,
)
from courses.services.progress import (
    upsert_course_progress,
    upsert_lesson_progress,
    upsert_module_progress,
)


def not_started_progress_payload() -> dict:
    return {"status": ProgressStatus.NOT_STARTED, "percent": 0}


def progress_payload(progress) -> dict:
    if progress is None:
        return not_started_progress_payload()
    return {
        "status": progress.status,
        "percent": progress.percent,
    }


def is_answer_completed(task: CourseTask, answer: UserTaskAnswer | None) -> bool:
    if task.task_kind == CourseTaskKind.INFORMATIONAL:
        return True
    if answer is None:
        return False
    if task.check_type == CourseTaskCheckType.WITH_REVIEW:
        return answer.status == UserTaskAnswerStatus.ACCEPTED
    return bool(answer.is_correct)


def answers_by_task(user, tasks: list[CourseTask]) -> dict[int, UserTaskAnswer]:
    if not tasks:
        return {}
    task_ids = [task.id for task in tasks]
    answers = UserTaskAnswer.objects.filter(user=user, task_id__in=task_ids)
    return {answer.task_id: answer for answer in answers}


def task_completion_map(
    user,
    tasks: list[CourseTask],
) -> dict[int, bool]:
    answer_map = answers_by_task(user, tasks)
    return task_completion_map_from_answers(tasks, answer_map)


def task_completion_map_from_answers(
    tasks: list[CourseTask],
    answer_map: dict[int, UserTaskAnswer],
) -> dict[int, bool]:
    return {
        task.id: is_answer_completed(task, answer_map.get(task.id))
        for task in tasks
    }


def first_unfinished_task(
    tasks: list[CourseTask],
    completion_map: dict[int, bool],
) -> CourseTask | None:
    for task in tasks:
        if not completion_map.get(task.id, False):
            return task
    return None


def ensure_lesson_access(user, lesson: CourseLesson) -> None:
    module = lesson.module
    course = module.course
    course_availability = resolve_course_availability(course, user)
    modules = list(
        course.modules.filter(status=CourseModuleContentStatus.PUBLISHED).order_by(
            "order", "id"
        )
    )
    module_progress_map = {
        progress.module_id: progress
        for progress in UserModuleProgress.objects.filter(
            user=user, module_id__in=[item.id for item in modules]
        )
    }

    previous_module_completed = True
    module_available = False
    for ordered_module in modules:
        module_progress = module_progress_map.get(ordered_module.id)
        module_completed = bool(
            module_progress
            and module_progress.status == ProgressStatus.COMPLETED
        )
        ordered_module_available = is_module_available(
            ordered_module,
            course_available=course_availability.is_available,
            previous_module_completed=previous_module_completed,
        )
        if ordered_module.id == module.id:
            module_available = ordered_module_available
            break
        previous_module_completed = module_completed

    lessons = list(
        module.lessons.filter(status=CourseLessonContentStatus.PUBLISHED).order_by(
            "order", "id"
        )
    )
    lesson_progress_map = {
        progress.lesson_id: progress
        for progress in UserLessonProgress.objects.filter(
            user=user, lesson_id__in=[item.id for item in lessons]
        )
    }

    previous_lesson_completed = True
    lesson_available = False
    for ordered_lesson in lessons:
        lesson_progress = lesson_progress_map.get(ordered_lesson.id)
        lesson_completed = bool(
            lesson_progress
            and lesson_progress.status == ProgressStatus.COMPLETED
        )
        ordered_lesson_available = is_lesson_available(
            ordered_lesson,
            module_available=module_available,
            previous_lesson_completed=previous_lesson_completed,
        )
        if ordered_lesson.id == lesson.id:
            lesson_available = ordered_lesson_available
            break
        previous_lesson_completed = lesson_completed

    if not lesson_available:
        raise PermissionDenied("Урок пока недоступен.")


def ensure_task_submission_access(user, task: CourseTask) -> None:
    lesson = task.lesson
    ensure_lesson_access(user, lesson)

    tasks = list(
        lesson.tasks.filter(status=CourseTaskContentStatus.PUBLISHED).order_by(
            "order", "id"
        )
    )
    completion_map = task_completion_map(user, tasks)
    current_task = first_unfinished_task(tasks, completion_map)
    if current_task is None:
        raise PermissionDenied("Все задания в уроке уже завершены.")
    if current_task.id != task.id:
        raise PermissionDenied(
            "Задание недоступно для отправки: необходимо соблюдать порядок."
        )


def recalculate_user_progresses_for_lesson(user, lesson: CourseLesson) -> None:
    module = lesson.module
    course = module.course

    # Recalculate only the touched lesson from its published tasks.
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

    # Module progress depends on completed lesson progresses inside this module.
    module_total_lessons = module.lessons.filter(
        status=CourseLessonContentStatus.PUBLISHED
    ).count()
    module_completed_lessons = UserLessonProgress.objects.filter(
        user=user,
        lesson__module=module,
        lesson__status=CourseLessonContentStatus.PUBLISHED,
        status=ProgressStatus.COMPLETED,
    ).count()
    upsert_module_progress(
        user,
        module,
        completed_lessons=module_completed_lessons,
        total_lessons=module_total_lessons,
    )

    # Course progress depends on completed lesson progresses across published modules.
    course_total_lessons = CourseLesson.objects.filter(
        module__course=course,
        module__status=CourseModuleContentStatus.PUBLISHED,
        status=CourseLessonContentStatus.PUBLISHED,
    ).count()
    course_completed_lessons = UserLessonProgress.objects.filter(
        user=user,
        lesson__module__course=course,
        lesson__module__status=CourseModuleContentStatus.PUBLISHED,
        lesson__status=CourseLessonContentStatus.PUBLISHED,
        status=ProgressStatus.COMPLETED,
    ).count()
    upsert_course_progress(
        user,
        course,
        completed_lessons=course_completed_lessons,
        total_lessons=course_total_lessons,
    )
