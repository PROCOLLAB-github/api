"""Внутренний адаптер будущего квиза; публичных способов ввода балла нет."""

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from rest_framework.exceptions import APIException, ValidationError

from partner_programs.overall_models import ProgramQuizOutcome, normalized_stage_score
from projects.team_policy import lock_team


class QuizOutcomeConflict(APIException):
    status_code = 409
    default_code = "quiz_outcome_conflict"
    default_detail = "У команды уже есть другой результат завершенного квиза."


@transaction.atomic
def record_quiz_outcome(program_id, project_id, source_attempt_id, score):
    """Вызывать только серверным модулем после завершения и расчета попытки.

    ID попытки глобально уникален; при локальных ID модуль добавляет свой namespace.
    Повтор того же события не меняет балл/время и не создает вторую запись.
    """
    try:
        value = normalized_stage_score(score)
    except ModelValidationError as error:
        raise ValidationError({"score": error.messages}) from error
    if (
        not isinstance(source_attempt_id, str)
        or not source_attempt_id.strip()
        or source_attempt_id != source_attempt_id.strip()
        or len(source_attempt_id) > 128
    ):
        raise ValidationError(
            {"source_attempt_id": "Укажите непустой идентификатор до 128 символов."}
        )
    context = lock_team(project_id, extra_program_ids=[program_id])
    program = context.programs.get(program_id)
    if program is None or not any(
        link.partner_program_id == program_id for link in context.links
    ):
        raise Http404
    if not program.is_competitive or program.solution_storage_mode != "legacy_project":
        raise ValidationError(
            "Результат квиза поддерживается для конкурсной программы с проектами."
        )
    existing = ProgramQuizOutcome.objects.filter(
        program=program, project=context.project
    ).first()
    if existing:
        if existing.source_attempt_id == source_attempt_id and existing.score == value:
            return existing
        raise QuizOutcomeConflict()
    if ProgramQuizOutcome.objects.filter(source_attempt_id=source_attempt_id).exists():
        raise QuizOutcomeConflict("Эта попытка уже относится к другой команде.")
    outcome = ProgramQuizOutcome(
        program=program,
        project=context.project,
        source_attempt_id=source_attempt_id,
        score=value,
    )
    try:
        with transaction.atomic():
            outcome.save()
    except (IntegrityError, ModelValidationError) as error:
        if ProgramQuizOutcome.objects.filter(
            source_attempt_id=source_attempt_id
        ).exists():
            raise QuizOutcomeConflict(
                "Эта попытка уже относится к другой команде."
            ) from error
        if ProgramQuizOutcome.objects.filter(
            program=program, project=context.project
        ).exists():
            raise QuizOutcomeConflict() from error
        if isinstance(error, ModelValidationError):
            raise ValidationError(
                getattr(error, "message_dict", error.messages)
            ) from error
        raise
    return outcome
