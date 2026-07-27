# Roadmap: DEV-050, DEV-051, DEV-052
# Контур экспертного доступа к Submission и управления Evaluation.

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Prefetch, Subquery
from django.utils import timezone

from partner_programs.models import (
    Evaluation,
    EvaluationScore,
    PartnerProgram,
    Submission,
    SubmissionExpertAssignment,
)
from project_rates.models import Criteria
from users.models import Expert


class EvaluationServiceError(Exception):
    code = "evaluation_error"
    default_detail = "Не удалось выполнить операцию с оценкой."
    field = None

    def __init__(self, detail=None, *, field=None):
        self.detail = detail or self.default_detail
        self.field = field if field is not None else self.field
        super().__init__(self.detail)


class EvaluationAccessDeniedError(EvaluationServiceError):
    code = "evaluation_access_denied"
    default_detail = "Доступ к экспертному контуру запрещён."


class EvaluationNotFoundError(EvaluationServiceError):
    code = "evaluation_not_found"
    default_detail = "Оценка или назначенное решение не найдено."


class EvaluationValidationError(EvaluationServiceError):
    code = "evaluation_validation"


class EvaluationConflictError(EvaluationServiceError):
    code = "evaluation_conflict"


class AssignmentUnavailableError(EvaluationConflictError):
    code = "assignment_unavailable"
    default_detail = "Активное назначение эксперта недоступно."


class SubmissionUnavailableError(EvaluationConflictError):
    code = "submission_unavailable"
    default_detail = "Оценивать можно только отправленное или финальное решение."


class EvaluationSubmittedError(EvaluationConflictError):
    code = "evaluation_submitted"
    default_detail = "Отправленная оценка недоступна для изменения."


@dataclass(frozen=True)
class EvaluationCreationResult:
    evaluation: Evaluation
    created: bool


@dataclass(frozen=True)
class ExpertSubmissionDetailResult:
    submission: Submission
    assignment: SubmissionExpertAssignment
    evaluation: Evaluation | None
    criteria: list[Criteria]


def get_numeric_criteria(program: PartnerProgram):
    return Criteria.objects.filter(
        partner_program=program,
        type__in=EvaluationScore.NUMERIC_CRITERION_TYPES,
    ).order_by("id")


def _expert_for_user(user, *, list_access=False):
    try:
        return user.expert
    except Expert.DoesNotExist as exc:
        error_class = (
            EvaluationAccessDeniedError if list_access else EvaluationNotFoundError
        )
        raise error_class() from exc


def _require_expert_membership(expert: Expert, program: PartnerProgram):
    if not expert.programs.filter(pk=program.pk).exists():
        raise EvaluationNotFoundError()


def _require_submission_status(submission: Submission):
    if submission.status not in (
        Submission.STATUS_SUBMITTED,
        Submission.STATUS_FINAL,
    ):
        raise SubmissionUnavailableError()


def _assignment_queryset(*, submission_id, expert_id, for_update=False):
    queryset = SubmissionExpertAssignment.objects.select_related(
        "submission",
        "submission__program",
        "expert",
    ).filter(
        submission_id=submission_id,
        expert_id=expert_id,
    )
    if for_update:
        queryset = queryset.select_for_update()
    return queryset.order_by("-created_at", "-id")


def _require_assigned_episode(*, submission_id, expert_id, for_update=False):
    queryset = _assignment_queryset(
        submission_id=submission_id,
        expert_id=expert_id,
        for_update=for_update,
    )
    assignment = queryset.filter(
        status=SubmissionExpertAssignment.STATUS_ASSIGNED
    ).first()
    if assignment is not None:
        return assignment
    if queryset.exists():
        raise AssignmentUnavailableError()
    raise EvaluationNotFoundError()


def _active_assignment(*, submission_id, expert_id):
    return (
        _assignment_queryset(
            submission_id=submission_id,
            expert_id=expert_id,
        )
        .filter(status__in=SubmissionExpertAssignment.ACTIVE_STATUSES)
        .first()
    )


def expert_submission_assignments(*, user):
    expert = _expert_for_user(user, list_access=True)
    evaluation = Evaluation.objects.filter(
        submission_id=OuterRef("submission_id"),
        expert_id=expert.pk,
    )
    return (
        SubmissionExpertAssignment.objects.filter(
            expert=expert,
            status__in=SubmissionExpertAssignment.ACTIVE_STATUSES,
            submission__program__experts=expert,
        )
        .select_related(
            "submission",
            "submission__program",
        )
        .annotate(
            my_evaluation_id=Subquery(evaluation.values("id")[:1]),
            my_evaluation_status=Subquery(evaluation.values("status")[:1]),
            my_evaluation_updated_at=Subquery(evaluation.values("updated_at")[:1]),
            my_evaluation_submitted_at=Subquery(evaluation.values("submitted_at")[:1]),
        )
        .order_by("-assigned_at", "-id")
    )


def get_expert_submission_detail(*, submission_id, user):
    submission = (
        Submission.objects.select_related("program").filter(pk=submission_id).first()
    )
    if submission is None:
        raise EvaluationNotFoundError()

    if user.is_staff or user.is_superuser:
        assignment = (
            SubmissionExpertAssignment.objects.select_related("expert")
            .filter(
                submission=submission,
                status__in=SubmissionExpertAssignment.ACTIVE_STATUSES,
            )
            .order_by("-created_at", "-id")
            .first()
        )
    else:
        expert = _expert_for_user(user)
        assignment = _active_assignment(
            submission_id=submission.pk,
            expert_id=expert.pk,
        )
        if assignment is not None:
            _require_expert_membership(expert, submission.program)
    if assignment is None:
        raise EvaluationNotFoundError()

    evaluation = (
        Evaluation.objects.prefetch_related(
            Prefetch(
                "scores",
                queryset=EvaluationScore.objects.select_related("criterion").order_by(
                    "criterion_id"
                ),
            )
        )
        .filter(
            submission=submission,
            expert_id=assignment.expert_id,
        )
        .first()
    )
    return ExpertSubmissionDetailResult(
        submission=submission,
        assignment=assignment,
        evaluation=evaluation,
        criteria=list(get_numeric_criteria(submission.program)),
    )


def get_my_evaluation(*, submission_id, user):
    expert = _expert_for_user(user)
    assignment = _active_assignment(
        submission_id=submission_id,
        expert_id=expert.pk,
    )
    if assignment is None:
        raise EvaluationNotFoundError()
    _require_expert_membership(expert, assignment.submission.program)
    evaluation = (
        Evaluation.objects.select_related(
            "submission",
            "submission__program",
            "expert",
            "expert__user",
        )
        .prefetch_related(
            Prefetch(
                "scores",
                queryset=EvaluationScore.objects.select_related("criterion").order_by(
                    "criterion_id"
                ),
            )
        )
        .filter(
            submission_id=submission_id,
            expert=expert,
        )
        .first()
    )
    if evaluation is None:
        raise EvaluationNotFoundError()
    return evaluation


def _validated_scores(*, program, scores):
    criterion_ids = [item["criterion_id"] for item in scores]
    if len(criterion_ids) != len(set(criterion_ids)):
        raise EvaluationValidationError(
            "Критерии в scores не должны повторяться.",
            field="scores",
        )

    criteria = {
        criterion.pk: criterion
        for criterion in Criteria.objects.filter(pk__in=criterion_ids)
    }
    validated = []
    for item in scores:
        criterion = criteria.get(item["criterion_id"])
        if criterion is None:
            raise EvaluationValidationError(
                "Указан неизвестный критерий.",
                field="scores",
            )
        if criterion.partner_program_id != program.pk:
            raise EvaluationValidationError(
                "Критерий относится к другой программе.",
                field="scores",
            )
        if criterion.type not in EvaluationScore.NUMERIC_CRITERION_TYPES:
            raise EvaluationValidationError(
                "В scores разрешены только числовые критерии.",
                field="scores",
            )

        value = item["value"]
        if criterion.type == "int" and value != value.to_integral_value():
            raise EvaluationValidationError(
                "Для целочисленного критерия требуется целое значение.",
                field="scores",
            )
        if criterion.min_value is not None and value < Decimal(str(criterion.min_value)):
            raise EvaluationValidationError(
                f"Значение критерия {criterion.pk} меньше допустимого минимума.",
                field="scores",
            )
        if criterion.max_value is not None and value > Decimal(str(criterion.max_value)):
            raise EvaluationValidationError(
                f"Значение критерия {criterion.pk} больше допустимого максимума.",
                field="scores",
            )
        validated.append((criterion, value))
    return validated


def _replace_scores(*, evaluation, validated_scores):
    evaluation.scores.all().delete()
    for criterion, value in validated_scores:
        EvaluationScore.objects.create(
            evaluation=evaluation,
            criterion=criterion,
            value=value,
        )


def _existing_creation_result(evaluation):
    if evaluation.status == Evaluation.STATUS_SUBMITTED:
        raise EvaluationSubmittedError()
    return EvaluationCreationResult(
        evaluation=evaluation,
        created=False,
    )


def create_or_get_draft_evaluation(
    *,
    submission_id,
    user,
    comment="",
    scores=None,
):
    expert = _expert_for_user(user)
    with transaction.atomic():
        assignment = _require_assigned_episode(
            submission_id=submission_id,
            expert_id=expert.pk,
            for_update=True,
        )
        submission = assignment.submission
        _require_expert_membership(expert, submission.program)
        _require_submission_status(submission)

        existing = (
            Evaluation.objects.select_for_update()
            .filter(submission=submission, expert=expert)
            .first()
        )
        if existing is not None:
            return _existing_creation_result(existing)

        validated_scores = _validated_scores(
            program=submission.program,
            scores=scores or [],
        )
        try:
            with transaction.atomic():
                evaluation = Evaluation.objects.create(
                    submission=submission,
                    expert=expert,
                    comment=comment,
                )
        except (IntegrityError, DjangoValidationError) as exc:
            existing = (
                Evaluation.objects.select_for_update()
                .filter(submission=submission, expert=expert)
                .first()
            )
            if existing is not None:
                return _existing_creation_result(existing)
            raise EvaluationConflictError(
                "Оценка изменилась конкурентно. Повторите запрос."
            ) from exc

        _replace_scores(
            evaluation=evaluation,
            validated_scores=validated_scores,
        )
        return EvaluationCreationResult(
            evaluation=evaluation,
            created=True,
        )


def _evaluation_identity_for_owner(*, evaluation_id, user):
    expert = _expert_for_user(user)
    evaluation = (
        Evaluation.objects.select_related("submission", "submission__program")
        .filter(pk=evaluation_id, expert=expert)
        .first()
    )
    if evaluation is None:
        raise EvaluationNotFoundError()
    _require_expert_membership(expert, evaluation.submission.program)
    return evaluation, expert


def update_draft_evaluation(
    *,
    evaluation_id,
    user,
    comment_supplied=False,
    comment="",
    scores_supplied=False,
    scores=None,
):
    identity, expert = _evaluation_identity_for_owner(
        evaluation_id=evaluation_id,
        user=user,
    )
    with transaction.atomic():
        _require_assigned_episode(
            submission_id=identity.submission_id,
            expert_id=expert.pk,
            for_update=True,
        )
        evaluation = (
            Evaluation.objects.select_for_update()
            .select_related("submission", "submission__program")
            .get(pk=identity.pk)
        )
        if evaluation.status == Evaluation.STATUS_SUBMITTED:
            raise EvaluationSubmittedError()
        _require_submission_status(evaluation.submission)

        if scores_supplied:
            validated_scores = _validated_scores(
                program=evaluation.submission.program,
                scores=scores or [],
            )
            _replace_scores(
                evaluation=evaluation,
                validated_scores=validated_scores,
            )
        if comment_supplied:
            evaluation.comment = comment
        if comment_supplied or scores_supplied:
            evaluation.save(update_fields=["comment", "updated_at"])

        return evaluation


def _validate_complete_evaluation(*, evaluation):
    criteria = list(get_numeric_criteria(evaluation.submission.program))
    criteria_by_id = {criterion.pk: criterion for criterion in criteria}
    scores = list(evaluation.scores.select_related("criterion").all())
    score_ids = [score.criterion_id for score in scores]
    if len(score_ids) != len(set(score_ids)):
        raise EvaluationValidationError(
            "Критерии в оценке не должны повторяться.",
            field="scores",
        )
    if set(score_ids) != set(criteria_by_id):
        raise EvaluationValidationError(
            "Перед отправкой заполните все числовые критерии программы.",
            field="scores",
        )
    _validated_scores(
        program=evaluation.submission.program,
        scores=[
            {
                "criterion_id": score.criterion_id,
                "value": score.value,
            }
            for score in scores
        ],
    )


def submit_evaluation(*, evaluation_id, user):
    identity, expert = _evaluation_identity_for_owner(
        evaluation_id=evaluation_id,
        user=user,
    )
    with transaction.atomic():
        assignment = (
            _assignment_queryset(
                submission_id=identity.submission_id,
                expert_id=expert.pk,
                for_update=True,
            )
            .filter(status__in=SubmissionExpertAssignment.ACTIVE_STATUSES)
            .first()
        )
        if assignment is None:
            if _assignment_queryset(
                submission_id=identity.submission_id,
                expert_id=expert.pk,
                for_update=True,
            ).exists():
                raise AssignmentUnavailableError()
            raise EvaluationNotFoundError()

        evaluation = (
            Evaluation.objects.select_for_update()
            .select_related("submission", "submission__program")
            .get(pk=identity.pk)
        )
        if evaluation.status == Evaluation.STATUS_SUBMITTED:
            return evaluation
        if assignment.status != SubmissionExpertAssignment.STATUS_ASSIGNED:
            raise AssignmentUnavailableError()
        _require_submission_status(evaluation.submission)
        _validate_complete_evaluation(evaluation=evaluation)

        now = timezone.now()
        evaluation.status = Evaluation.STATUS_SUBMITTED
        evaluation.submitted_at = now
        evaluation.total_score = None
        evaluation.save(
            update_fields=[
                "status",
                "submitted_at",
                "total_score",
                "updated_at",
            ]
        )

        assignment.status = SubmissionExpertAssignment.STATUS_COMPLETED
        assignment.completed_at = now
        assignment.save(
            update_fields=[
                "status",
                "completed_at",
                "updated_at",
            ]
        )
        return evaluation


def get_visible_evaluation(*, evaluation_id, user):
    evaluation = (
        Evaluation.objects.select_related(
            "submission",
            "submission__program",
            "expert",
            "expert__user",
        )
        .prefetch_related(
            Prefetch(
                "scores",
                queryset=EvaluationScore.objects.select_related("criterion").order_by(
                    "criterion_id"
                ),
            )
        )
        .filter(pk=evaluation_id)
        .first()
    )
    if evaluation is None:
        raise EvaluationNotFoundError()
    if user.is_staff or user.is_superuser:
        return evaluation
    try:
        expert = user.expert
    except Expert.DoesNotExist:
        expert = None
    if (
        expert is not None
        and evaluation.expert_id == expert.pk
        and expert.programs.filter(pk=evaluation.submission.program_id).exists()
        and _active_assignment(
            submission_id=evaluation.submission_id,
            expert_id=expert.pk,
        )
        is not None
    ):
        return evaluation
    if evaluation.submission.program.is_manager(user):
        return evaluation
    raise EvaluationNotFoundError()


def manager_evaluations_queryset(*, program):
    latest_assignment = SubmissionExpertAssignment.objects.filter(
        submission_id=OuterRef("submission_id"),
        expert_id=OuterRef("expert_id"),
    ).order_by("-created_at", "-id")
    return (
        Evaluation.objects.filter(submission__program=program)
        .select_related(
            "submission",
            "submission__program",
            "expert",
            "expert__user",
        )
        .prefetch_related(
            Prefetch(
                "scores",
                queryset=EvaluationScore.objects.select_related("criterion").order_by(
                    "criterion_id"
                ),
            )
        )
        .annotate(
            assignment_id=Subquery(latest_assignment.values("id")[:1]),
            assignment_status=Subquery(latest_assignment.values("status")[:1]),
            assignment_assigned_at=Subquery(latest_assignment.values("assigned_at")[:1]),
            assignment_completed_at=Subquery(
                latest_assignment.values("completed_at")[:1]
            ),
        )
        .order_by("-updated_at", "-id")
    )
