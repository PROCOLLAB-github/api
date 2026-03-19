from datetime import date, timedelta
from uuid import uuid4

from django.utils import timezone

from courses.models import (
    Course,
    CourseAccessType,
    CourseContentStatus,
    CourseLesson,
    CourseLessonContentStatus,
    CourseModule,
    CourseModuleContentStatus,
    CourseTask,
    CourseTaskAnswerType,
    CourseTaskCheckType,
    CourseTaskContentStatus,
    CourseTaskInformationalType,
    CourseTaskKind,
    CourseTaskOption,
    CourseTaskQuestionType,
)
from files.models import UserFile
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from users.models import CustomUser


def unique_suffix() -> str:
    return uuid4().hex[:8]


def create_user(*, prefix: str = "courses-test") -> CustomUser:
    suffix = unique_suffix()
    return CustomUser.objects.create_user(
        email=f"{prefix}-{suffix}@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
        birthday="2000-01-01",
        is_active=True,
    )


def create_staff_user(*, prefix: str = "courses-admin") -> CustomUser:
    suffix = unique_suffix()
    return CustomUser.objects.create_superuser(
        email=f"{prefix}-{suffix}@example.com",
        password="testpass123",
        first_name="Admin",
        last_name="User",
    )


def create_partner_program(*, name: str = "Program") -> PartnerProgram:
    suffix = unique_suffix()
    now = timezone.now()
    return PartnerProgram.objects.create(
        name=f"{name} {suffix}",
        tag=f"program-{suffix}",
        city="Moscow",
        datetime_registration_ends=now + timedelta(days=10),
        datetime_started=now - timedelta(days=1),
        datetime_finished=now + timedelta(days=30),
        draft=False,
    )


def add_program_member(program: PartnerProgram, user: CustomUser) -> None:
    PartnerProgramUserProfile.objects.create(
        user=user,
        partner_program=program,
        project=None,
        partner_program_data={},
    )


def create_course(
    *,
    title: str = "Course",
    access_type: str = CourseAccessType.ALL_USERS,
    status: str = CourseContentStatus.PUBLISHED,
    partner_program: PartnerProgram | None = None,
) -> Course:
    suffix = unique_suffix()
    return Course.objects.create(
        title=f"{title} {suffix}",
        access_type=access_type,
        status=status,
        partner_program=partner_program,
    )


def create_module(
    course: Course,
    *,
    title: str = "Module",
    order: int = 1,
    status: str = CourseModuleContentStatus.PUBLISHED,
    start_date_value: date | None = None,
) -> CourseModule:
    return CourseModule.objects.create(
        course=course,
        title=title,
        start_date=start_date_value or date.today(),
        status=status,
        order=order,
    )


def create_lesson(
    module: CourseModule,
    *,
    title: str = "Lesson",
    order: int = 1,
    status: str = CourseLessonContentStatus.PUBLISHED,
) -> CourseLesson:
    return CourseLesson.objects.create(
        module=module,
        title=title,
        status=status,
        order=order,
    )


def create_informational_task(
    lesson: CourseLesson,
    *,
    title: str = "Info",
    order: int = 1,
) -> CourseTask:
    return CourseTask.objects.create(
        lesson=lesson,
        title=title,
        status=CourseTaskContentStatus.PUBLISHED,
        task_kind=CourseTaskKind.INFORMATIONAL,
        informational_type=CourseTaskInformationalType.TEXT,
        body_text="Read this",
        order=order,
    )


def create_text_question_task(
    lesson: CourseLesson,
    *,
    title: str = "Question",
    order: int = 1,
    check_type: str = CourseTaskCheckType.WITHOUT_REVIEW,
) -> CourseTask:
    return CourseTask.objects.create(
        lesson=lesson,
        title=title,
        status=CourseTaskContentStatus.PUBLISHED,
        task_kind=CourseTaskKind.QUESTION,
        question_type=CourseTaskQuestionType.TEXT,
        answer_type=CourseTaskAnswerType.TEXT,
        check_type=check_type,
        body_text="Answer this",
        order=order,
    )


def create_user_file(
    user: CustomUser,
    *,
    name: str = "attachment",
    extension: str = "pdf",
    mime_type: str = "application/pdf",
    size: int = 1024,
) -> UserFile:
    suffix = unique_suffix()
    return UserFile.objects.create(
        link=f"https://cdn.example.com/tests/{suffix}/{name}.{extension}",
        user=user,
        name=name,
        extension=extension,
        mime_type=mime_type,
        size=size,
    )


def create_choice_question_task(
    lesson: CourseLesson,
    *,
    title: str,
    order: int,
    answer_type: str,
    options: list[tuple[str, bool]],
    body_text: str = "Выберите правильный вариант.",
) -> tuple[CourseTask, list[CourseTaskOption]]:
    task = CourseTask.objects.create(
        lesson=lesson,
        title=title,
        status=CourseTaskContentStatus.DRAFT,
        task_kind=CourseTaskKind.QUESTION,
        question_type=CourseTaskQuestionType.TEXT,
        answer_type=answer_type,
        check_type=CourseTaskCheckType.WITHOUT_REVIEW,
        body_text=body_text,
        order=order,
    )
    created_options = []
    for option_order, (text, is_correct) in enumerate(options, start=1):
        created_options.append(
            CourseTaskOption.objects.create(
                task=task,
                order=option_order,
                text=text,
                is_correct=is_correct,
            )
        )
    task.status = CourseTaskContentStatus.PUBLISHED
    task.save()
    return task, created_options


def create_files_question_task(
    lesson: CourseLesson,
    *,
    attachment_file: UserFile,
    title: str = "Files question",
    order: int = 1,
) -> CourseTask:
    return CourseTask.objects.create(
        lesson=lesson,
        title=title,
        status=CourseTaskContentStatus.PUBLISHED,
        task_kind=CourseTaskKind.QUESTION,
        question_type=CourseTaskQuestionType.TEXT_FILE,
        answer_type=CourseTaskAnswerType.FILES,
        check_type=CourseTaskCheckType.WITHOUT_REVIEW,
        body_text="Приложите файл.",
        attachment_file=attachment_file,
        order=order,
    )


def create_text_and_files_question_task(
    lesson: CourseLesson,
    *,
    title: str = "Text and files question",
    order: int = 1,
) -> CourseTask:
    return CourseTask.objects.create(
        lesson=lesson,
        title=title,
        status=CourseTaskContentStatus.PUBLISHED,
        task_kind=CourseTaskKind.QUESTION,
        question_type=CourseTaskQuestionType.TEXT,
        answer_type=CourseTaskAnswerType.TEXT_AND_FILES,
        check_type=CourseTaskCheckType.WITHOUT_REVIEW,
        body_text="Текст и файл обязательны.",
        order=order,
    )


def create_course_tree(
    *,
    module_count: int = 1,
    lesson_count: int = 1,
    task_count: int = 2,
    access_type: str = CourseAccessType.ALL_USERS,
    partner_program: PartnerProgram | None = None,
) -> Course:
    course = create_course(
        title="Tree Course",
        access_type=access_type,
        partner_program=partner_program,
    )
    for module_order in range(1, module_count + 1):
        module = create_module(course, title=f"Module {module_order}", order=module_order)
        for lesson_order in range(1, lesson_count + 1):
            lesson = create_lesson(
                module,
                title=f"Lesson {module_order}.{lesson_order}",
                order=lesson_order,
            )
            for task_order in range(1, task_count + 1):
                if task_order == 1:
                    create_informational_task(
                        lesson,
                        title=f"Info {module_order}.{lesson_order}",
                        order=task_order,
                    )
                else:
                    create_text_question_task(
                        lesson,
                        title=f"Question {module_order}.{lesson_order}.{task_order}",
                        order=task_order,
                    )
    return course
