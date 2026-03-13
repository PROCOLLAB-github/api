from dataclasses import dataclass, field

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from files.models import UserFile

from courses.models import (
    CourseTask,
    CourseTaskAnswerType,
    CourseTaskCheckType,
    CourseTaskContentStatus,
    CourseTaskKind,
    CourseTaskOption,
    UserTaskAnswer,
    UserTaskAnswerFile,
    UserTaskAnswerOption,
    UserTaskAnswerStatus,
)
from courses.models.constants import DEFAULT_MAX_FILES_PER_ANSWER


@dataclass(slots=True)
class TaskAnswerSubmitPayload:
    answer_text: str = ""
    option_ids: list[int] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SubmitAnswerResult:
    answer: UserTaskAnswer
    is_correct: bool | None
    can_continue: bool
    next_task_id: int | None


def _is_non_empty_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _resolve_task_options(
    task: CourseTask, option_ids: list[int]
) -> list[CourseTaskOption]:
    if not option_ids:
        return []

    unique_ids = list(dict.fromkeys(option_ids))
    if len(unique_ids) != len(option_ids):
        raise ValidationError({"option_ids": "Переданы дублирующиеся варианты ответа."})

    options = list(task.options.filter(id__in=unique_ids))
    found_ids = {option.id for option in options}
    missing_ids = [option_id for option_id in unique_ids if option_id not in found_ids]
    if missing_ids:
        raise ValidationError(
            {"option_ids": f"Некоторые варианты ответа не найдены: {missing_ids}"}
        )
    return options


def _resolve_user_files(file_ids: list[str]) -> list[UserFile]:
    if not file_ids:
        return []

    unique_ids = list(dict.fromkeys(file_ids))
    if len(unique_ids) != len(file_ids):
        raise ValidationError({"file_ids": "Переданы дублирующиеся файлы."})

    files = list(UserFile.objects.filter(pk__in=unique_ids))
    files_by_id = {file.pk: file for file in files}
    missing_ids = [file_id for file_id in unique_ids if file_id not in files_by_id]
    if missing_ids:
        raise ValidationError({"file_ids": f"Некоторые файлы не найдены: {missing_ids}"})
    return [files_by_id[file_id] for file_id in unique_ids]


def _validate_payload_by_answer_type(
    task: CourseTask,
    payload: TaskAnswerSubmitPayload,
    *,
    options: list[CourseTaskOption],
    files: list[UserFile],
) -> None:
    answer_type = task.answer_type
    text_filled = _is_non_empty_text(payload.answer_text)

    if len(files) > DEFAULT_MAX_FILES_PER_ANSWER:
        raise ValidationError(
            {"file_ids": f"Максимум файлов в ответе: {DEFAULT_MAX_FILES_PER_ANSWER}."}
        )

    if answer_type == CourseTaskAnswerType.SINGLE_CHOICE and len(options) != 1:
        raise ValidationError(
            {"option_ids": "Для single_choice требуется выбрать ровно один вариант."}
        )

    if answer_type == CourseTaskAnswerType.MULTIPLE_CHOICE and not options:
        raise ValidationError(
            {"option_ids": "Для multiple_choice требуется выбрать хотя бы один вариант."}
        )

    if (
        answer_type
        in (
            CourseTaskAnswerType.SINGLE_CHOICE,
            CourseTaskAnswerType.MULTIPLE_CHOICE,
            CourseTaskAnswerType.FILES,
        )
        and text_filled
    ):
        raise ValidationError(
            {"answer_text": "Для этого типа ответа текст не используется."}
        )

    if answer_type == CourseTaskAnswerType.TEXT and not text_filled:
        raise ValidationError({"answer_text": "Для этого типа ответа требуется текст."})

    if answer_type == CourseTaskAnswerType.FILES and not files:
        raise ValidationError({"file_ids": "Для этого типа ответа требуется файл."})

    if answer_type == CourseTaskAnswerType.TEXT_AND_FILES:
        if not text_filled:
            raise ValidationError(
                {"answer_text": "Для этого типа ответа требуется текст."}
            )
        if not files:
            raise ValidationError({"file_ids": "Для этого типа ответа требуется файл."})

    if (
        answer_type
        in (
            CourseTaskAnswerType.TEXT,
            CourseTaskAnswerType.FILES,
            CourseTaskAnswerType.TEXT_AND_FILES,
        )
        and options
    ):
        raise ValidationError(
            {"option_ids": "Выбор варианта недопустим для этого типа ответа."}
        )


def _evaluate_answer(
    task: CourseTask,
    *,
    normalized_text: str,
    options: list[CourseTaskOption],
    files: list[UserFile],
) -> bool:
    if task.answer_type == CourseTaskAnswerType.SINGLE_CHOICE:
        return bool(options and options[0].is_correct)

    if task.answer_type == CourseTaskAnswerType.MULTIPLE_CHOICE:
        selected_ids = {option.id for option in options}
        correct_ids = set(
            task.options.filter(is_correct=True).values_list("id", flat=True)
        )
        return bool(selected_ids and selected_ids == correct_ids)

    if task.answer_type == CourseTaskAnswerType.TEXT:
        return _is_non_empty_text(normalized_text)

    if task.answer_type == CourseTaskAnswerType.FILES:
        return bool(files)

    if task.answer_type == CourseTaskAnswerType.TEXT_AND_FILES:
        return _is_non_empty_text(normalized_text) and bool(files)

    return False


def get_next_published_task(task: CourseTask) -> CourseTask | None:
    return (
        task.lesson.tasks.filter(
            status=CourseTaskContentStatus.PUBLISHED,
            order__gt=task.order,
        )
        .order_by("order", "id")
        .first()
    )


def _locked_answer_manager():
    manager = UserTaskAnswer.objects
    if transaction.get_connection().in_atomic_block:
        manager = manager.select_for_update()
    return manager


def _get_or_build_answer(user, task: CourseTask) -> UserTaskAnswer:
    answer = _locked_answer_manager().filter(user=user, task=task).first()
    if answer is not None:
        return answer
    return UserTaskAnswer(user=user, task=task)


def _apply_common_answer_fields(
    answer: UserTaskAnswer,
    *,
    answer_text: str,
    submitted_at,
) -> None:
    answer.answer_text = answer_text
    answer.submitted_at = submitted_at
    answer.review_comment = ""
    answer.reviewed_by = None
    answer.reviewed_at = None


def _save_answer_with_retry(answer: UserTaskAnswer, configure_answer) -> UserTaskAnswer:
    configure_answer(answer)
    try:
        answer.save(validate=False)
        return answer
    except DjangoValidationError as exc:
        if hasattr(exc, "message_dict"):
            raise ValidationError(exc.message_dict) from exc
        raise ValidationError({"detail": exc.messages}) from exc
    except IntegrityError:
        retry_answer = _locked_answer_manager().get(user=answer.user, task=answer.task)
        configure_answer(retry_answer)
        retry_answer.save(validate=False)
        return retry_answer


def _replace_answer_relations(
    answer: UserTaskAnswer,
    *,
    selected_options: list[CourseTaskOption],
    selected_files: list[UserFile],
) -> None:
    answer.selected_options.all().delete()
    answer.files.all().delete()

    if selected_options:
        UserTaskAnswerOption.objects.bulk_create(
            [
                UserTaskAnswerOption(answer=answer, option=option)
                for option in selected_options
            ]
        )

    if selected_files:
        UserTaskAnswerFile.objects.bulk_create(
            [
                UserTaskAnswerFile(
                    answer=answer,
                    file=user_file,
                    file_name=user_file.name,
                    file_size=user_file.size,
                )
                for user_file in selected_files
            ]
        )


def _build_submit_result(
    answer: UserTaskAnswer,
    *,
    can_continue: bool,
) -> SubmitAnswerResult:
    next_task = get_next_published_task(answer.task) if can_continue else None
    return SubmitAnswerResult(
        answer=answer,
        is_correct=answer.is_correct,
        can_continue=can_continue,
        next_task_id=next_task.id if next_task else None,
    )


def _submit_informational_answer(
    user,
    task: CourseTask,
    *,
    submitted_at,
) -> SubmitAnswerResult:
    answer = _get_or_build_answer(user, task)

    def configure_answer(current_answer: UserTaskAnswer) -> None:
        _apply_common_answer_fields(
            current_answer,
            answer_text="",
            submitted_at=submitted_at,
        )
        current_answer.status = UserTaskAnswerStatus.SUBMITTED
        current_answer.is_correct = True

    answer = _save_answer_with_retry(answer, configure_answer)
    _replace_answer_relations(
        answer,
        selected_options=[],
        selected_files=[],
    )
    return _build_submit_result(answer, can_continue=True)


def _validate_question_task(task: CourseTask) -> None:
    if not task.answer_type:
        raise ValidationError({"task": "У задания не задан тип ответа."})
    if not task.check_type:
        raise ValidationError({"task": "У задания не задан тип проверки."})


def _resolve_question_payload(
    task: CourseTask,
    payload: TaskAnswerSubmitPayload,
) -> tuple[str, list[CourseTaskOption], list[UserFile]]:
    selected_options = _resolve_task_options(task, payload.option_ids)
    selected_files = _resolve_user_files(payload.file_ids)
    _validate_payload_by_answer_type(
        task,
        payload,
        options=selected_options,
        files=selected_files,
    )
    normalized_text = (payload.answer_text or "").strip()
    return normalized_text, selected_options, selected_files


def _evaluate_question_submission(
    task: CourseTask,
    *,
    normalized_text: str,
    selected_options: list[CourseTaskOption],
    selected_files: list[UserFile],
) -> tuple[str, bool | None, bool]:
    if task.check_type == CourseTaskCheckType.WITH_REVIEW:
        return UserTaskAnswerStatus.PENDING_REVIEW, None, False

    is_correct = _evaluate_answer(
        task,
        normalized_text=normalized_text,
        options=selected_options,
        files=selected_files,
    )
    return UserTaskAnswerStatus.SUBMITTED, is_correct, bool(is_correct)


def _submit_question_answer(
    user,
    task: CourseTask,
    payload: TaskAnswerSubmitPayload,
    *,
    submitted_at,
) -> SubmitAnswerResult:
    _validate_question_task(task)
    normalized_text, selected_options, selected_files = _resolve_question_payload(
        task,
        payload,
    )
    status_value, is_correct, can_continue = _evaluate_question_submission(
        task,
        normalized_text=normalized_text,
        selected_options=selected_options,
        selected_files=selected_files,
    )
    answer = _get_or_build_answer(user, task)

    def configure_answer(current_answer: UserTaskAnswer) -> None:
        _apply_common_answer_fields(
            current_answer,
            answer_text=normalized_text,
            submitted_at=submitted_at,
        )
        current_answer.status = status_value
        current_answer.is_correct = is_correct

    answer = _save_answer_with_retry(answer, configure_answer)
    _replace_answer_relations(
        answer,
        selected_options=selected_options,
        selected_files=selected_files,
    )
    return _build_submit_result(answer, can_continue=can_continue)


def submit_user_task_answer(
    user,
    task: CourseTask,
    payload: TaskAnswerSubmitPayload,
) -> SubmitAnswerResult:
    if task.status != CourseTaskContentStatus.PUBLISHED:
        raise ValidationError(
            {"task": "Отправка ответа доступна только для опубликованных заданий."}
        )

    submitted_at = timezone.now()
    if task.task_kind == CourseTaskKind.INFORMATIONAL:
        return _submit_informational_answer(
            user,
            task,
            submitted_at=submitted_at,
        )
    return _submit_question_answer(
        user,
        task,
        payload,
        submitted_at=submitted_at,
    )
