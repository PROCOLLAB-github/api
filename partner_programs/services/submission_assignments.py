from dataclasses import dataclass

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from partner_programs.models import (
    Evaluation,
    PartnerProgram,
    Submission,
    SubmissionExpertAssignment,
)
from users.models import Expert


class SubmissionAssignmentServiceError(Exception):
    code = "submission_assignment_error"
    default_detail = "Unable to change the submission assignment."
    field = None

    def __init__(self, detail=None, *, field=None):
        self.detail = detail or self.default_detail
        self.field = field if field is not None else self.field
        super().__init__(self.detail)


class SubmissionAssignmentValidationError(SubmissionAssignmentServiceError):
    code = "invalid_assignment"


class SubmissionAssignmentConflictError(SubmissionAssignmentServiceError):
    code = "assignment_conflict"


class SubmissionStatusConflictError(SubmissionAssignmentConflictError):
    code = "submission_status_conflict"
    default_detail = "Only submitted or final submissions can be assigned."


class AssignmentCompletedError(SubmissionAssignmentConflictError):
    code = "assignment_completed"
    default_detail = "A completed assignment cannot be changed."


class SubmittedEvaluationExistsError(SubmissionAssignmentConflictError):
    code = "submitted_evaluation_exists"
    default_detail = "An assignment with a submitted evaluation cannot be revoked."


@dataclass(frozen=True)
class SubmissionAssignmentCreationResult:
    assignment: SubmissionExpertAssignment
    created: bool


def _get_active_assignment(*, submission_id, expert_id):
    return (
        SubmissionExpertAssignment.objects.filter(
            submission_id=submission_id,
            expert_id=expert_id,
            status__in=SubmissionExpertAssignment.ACTIVE_STATUSES,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def _result_for_existing_active(assignment):
    if assignment.status == SubmissionExpertAssignment.STATUS_COMPLETED:
        raise AssignmentCompletedError()
    return SubmissionAssignmentCreationResult(
        assignment=assignment,
        created=False,
    )


def _get_submission(*, program, submission_id):
    submission = (
        Submission.objects.select_for_update()
        .select_related("program")
        .filter(pk=submission_id)
        .first()
    )
    if submission is None:
        raise SubmissionAssignmentValidationError(
            "Submission not found.",
            field="submission_id",
        )
    if submission.program_id != program.pk:
        raise SubmissionAssignmentValidationError(
            "Submission does not belong to this program.",
            field="submission_id",
        )
    if submission.status not in (
        Submission.STATUS_SUBMITTED,
        Submission.STATUS_FINAL,
    ):
        raise SubmissionStatusConflictError()
    return submission


def _get_expert(*, program, expert_id):
    expert = Expert.objects.select_related("user").filter(pk=expert_id).first()
    if expert is None:
        raise SubmissionAssignmentValidationError(
            "Expert not found.",
            field="expert_id",
        )
    if not expert.programs.filter(pk=program.pk).exists():
        raise SubmissionAssignmentValidationError(
            "Expert does not belong to this program.",
            field="expert_id",
        )
    return expert


def create_submission_assignment(
    *,
    program: PartnerProgram,
    submission_id: int,
    expert_id: int,
    actor,
) -> SubmissionAssignmentCreationResult:
    with transaction.atomic():
        submission = _get_submission(
            program=program,
            submission_id=submission_id,
        )
        expert = _get_expert(program=program, expert_id=expert_id)

        existing = _get_active_assignment(
            submission_id=submission.pk,
            expert_id=expert.pk,
        )
        if existing is not None:
            return _result_for_existing_active(existing)

        try:
            with transaction.atomic():
                assignment = SubmissionExpertAssignment.objects.create(
                    submission=submission,
                    expert=expert,
                    assigned_by=actor,
                )
        except (IntegrityError, DjangoValidationError) as exc:
            existing = _get_active_assignment(
                submission_id=submission.pk,
                expert_id=expert.pk,
            )
            if existing is not None:
                return _result_for_existing_active(existing)
            raise SubmissionAssignmentConflictError(
                "The assignment changed concurrently. Please retry."
            ) from exc

        return SubmissionAssignmentCreationResult(
            assignment=assignment,
            created=True,
        )


def revoke_submission_assignment(
    *,
    assignment: SubmissionExpertAssignment,
    actor,
    reason: str,
) -> SubmissionExpertAssignment:
    reason = reason.strip()
    if not reason:
        raise SubmissionAssignmentValidationError(
            "A non-empty reason is required.",
            field="reason",
        )

    with transaction.atomic():
        assignment = (
            SubmissionExpertAssignment.objects.select_for_update()
            .select_related("submission", "expert")
            .get(pk=assignment.pk)
        )
        if assignment.status == SubmissionExpertAssignment.STATUS_REVOKED:
            return assignment
        if assignment.status == SubmissionExpertAssignment.STATUS_COMPLETED:
            raise AssignmentCompletedError()
        if Evaluation.objects.filter(
            submission_id=assignment.submission_id,
            expert_id=assignment.expert_id,
            status=Evaluation.STATUS_SUBMITTED,
        ).exists():
            raise SubmittedEvaluationExistsError()

        assignment.status = SubmissionExpertAssignment.STATUS_REVOKED
        assignment.revoked_by = actor
        assignment.revoked_at = timezone.now()
        assignment.revoke_reason = reason
        assignment.completed_at = None
        assignment.save(
            update_fields=[
                "status",
                "revoked_by",
                "revoked_at",
                "revoke_reason",
                "completed_at",
                "updated_at",
            ]
        )
        return assignment
