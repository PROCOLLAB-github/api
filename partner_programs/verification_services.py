from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from moderation.models import ModerationLog
from moderation.services import create_moderation_log
from notifications.services import (
    notify_verification_approved,
    notify_verification_rejected,
    notify_verification_submitted,
)
from partner_programs.models import PartnerProgram, PartnerProgramVerificationRequest


VERIFICATION_SUBMISSION_ALLOWED_STATUSES = {
    PartnerProgram.VERIFICATION_STATUS_NOT_REQUESTED,
    PartnerProgram.VERIFICATION_STATUS_REJECTED,
    PartnerProgram.VERIFICATION_STATUS_REVOKED,
}
REQUEST_STATUS_TO_PROGRAM_STATUS = {
    PartnerProgramVerificationRequest.STATUS_PENDING: PartnerProgram.VERIFICATION_STATUS_PENDING,
    PartnerProgramVerificationRequest.STATUS_APPROVED: PartnerProgram.VERIFICATION_STATUS_VERIFIED,
    PartnerProgramVerificationRequest.STATUS_REJECTED: PartnerProgram.VERIFICATION_STATUS_REJECTED,
}


class VerificationTransitionError(Exception):
    def __init__(self, current_status: str):
        self.current_status = current_status
        super().__init__(current_status)


def get_verification_rejection_reasons() -> list[dict[str, str]]:
    return [
        {"code": code, "label": label}
        for code, label in PartnerProgramVerificationRequest.REJECTION_REASON_CHOICES
    ]


@transaction.atomic
def submit_verification_request(
    *,
    program: PartnerProgram,
    author,
    company,
    company_name: str,
    inn: str,
    legal_name: str,
    ogrn: str,
    website: str,
    region: str,
    contact_full_name: str,
    contact_position: str,
    contact_email: str,
    contact_phone: str,
    company_role_description: str,
    documents,
) -> PartnerProgramVerificationRequest:
    current_status = effective_verification_status(program, author)
    if current_status not in VERIFICATION_SUBMISSION_ALLOWED_STATUSES:
        raise VerificationTransitionError(current_status)

    verification_request = PartnerProgramVerificationRequest.objects.create(
        program=program,
        company=company,
        company_name=company_name,
        inn=inn,
        legal_name=legal_name,
        ogrn=ogrn,
        website=website,
        region=region,
        initiator=author if getattr(author, "is_authenticated", False) else None,
        contact_full_name=contact_full_name,
        contact_position=contact_position,
        contact_email=contact_email,
        contact_phone=contact_phone,
        company_role_description=company_role_description,
    )
    verification_request.documents.set(documents)

    status_before = program.verification_status
    _sync_profile_programs_verification_status(
        user=author,
        company=company,
        status_value=PartnerProgram.VERIFICATION_STATUS_PENDING,
        fallback_program=program,
    )
    program.refresh_from_db(fields=["verification_status", "company", "datetime_updated"])

    create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_VERIFICATION_SUBMITTED,
        status_before=status_before,
        status_after=program.verification_status,
        comment=f"Verification request #{verification_request.id} submitted",
    )
    notify_verification_submitted(program, verification_request)
    return verification_request


@transaction.atomic
def approve_verification_request(
    *,
    verification_request: PartnerProgramVerificationRequest,
    author,
    comment: str = "",
) -> ModerationLog:
    if verification_request.status != PartnerProgramVerificationRequest.STATUS_PENDING:
        raise VerificationTransitionError(verification_request.status)

    program = verification_request.program
    status_before = program.verification_status
    now = timezone.now()

    verification_request.status = PartnerProgramVerificationRequest.STATUS_APPROVED
    verification_request.decided_at = now
    verification_request.decided_by = author
    verification_request.admin_comment = comment or ""
    verification_request.rejection_reason = ""
    verification_request.save(
        update_fields=[
            "status",
            "decided_at",
            "decided_by",
            "admin_comment",
            "rejection_reason",
            "datetime_updated",
        ]
    )

    _sync_profile_programs_verification_status(
        user=verification_request.initiator,
        company=verification_request.company,
        status_value=PartnerProgram.VERIFICATION_STATUS_VERIFIED,
        fallback_program=program,
    )
    program.refresh_from_db(fields=["verification_status", "company", "datetime_updated"])

    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_VERIFICATION_APPROVE,
        status_before=status_before,
        status_after=program.verification_status,
        comment=comment,
    )
    notify_verification_approved(verification_request)
    return log


@transaction.atomic
def reject_verification_request(
    *,
    verification_request: PartnerProgramVerificationRequest,
    author,
    comment: str,
    rejection_reason: str,
) -> ModerationLog:
    if verification_request.status != PartnerProgramVerificationRequest.STATUS_PENDING:
        raise VerificationTransitionError(verification_request.status)
    if not comment or not comment.strip():
        raise ValidationError({"comment": "Комментарий обязателен при отклонении."})

    valid_reasons = {reason["code"] for reason in get_verification_rejection_reasons()}
    if rejection_reason not in valid_reasons:
        raise ValidationError({"rejection_reason": "Некорректная причина отклонения."})

    program = verification_request.program
    status_before = program.verification_status
    now = timezone.now()

    verification_request.status = PartnerProgramVerificationRequest.STATUS_REJECTED
    verification_request.decided_at = now
    verification_request.decided_by = author
    verification_request.admin_comment = comment
    verification_request.rejection_reason = rejection_reason
    verification_request.save(
        update_fields=[
            "status",
            "decided_at",
            "decided_by",
            "admin_comment",
            "rejection_reason",
            "datetime_updated",
        ]
    )

    _sync_profile_programs_verification_status(
        user=verification_request.initiator,
        company=verification_request.company,
        status_value=PartnerProgram.VERIFICATION_STATUS_REJECTED,
        fallback_program=program,
    )
    program.refresh_from_db(fields=["verification_status", "company", "datetime_updated"])

    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_VERIFICATION_REJECT,
        status_before=status_before,
        status_after=program.verification_status,
        comment=comment,
        rejection_reason=rejection_reason,
    )
    notify_verification_rejected(verification_request)
    return log


@transaction.atomic
def revoke_program_verification(
    *,
    program: PartnerProgram,
    author,
    comment: str,
) -> ModerationLog:
    if program.verification_status != PartnerProgram.VERIFICATION_STATUS_VERIFIED:
        raise VerificationTransitionError(program.verification_status)
    if not comment or not comment.strip():
        raise ValidationError({"comment": "Комментарий обязателен при отзыве верификации."})

    status_before = program.verification_status
    program.verification_status = PartnerProgram.VERIFICATION_STATUS_REVOKED
    program.save(update_fields=["verification_status", "datetime_updated"])

    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_VERIFICATION_REVOKE,
        status_before=status_before,
        status_after=program.verification_status,
        comment=comment,
    )
    return log


def effective_verification_status(program: PartnerProgram, user=None) -> str:
    if program.verification_status == PartnerProgram.VERIFICATION_STATUS_REVOKED:
        return PartnerProgram.VERIFICATION_STATUS_REVOKED

    latest_request = latest_verification_request(program, user=user)
    if latest_request:
        return REQUEST_STATUS_TO_PROGRAM_STATUS.get(
            latest_request.status,
            program.verification_status,
        )

    return program.verification_status


def latest_verification_request(program: PartnerProgram, user=None):
    return (
        verification_requests_for_program(program, user=user)
        .select_related(
            "company",
            "initiator",
            "decided_by",
        )
        .prefetch_related("documents")
        .order_by("-submitted_at", "-id")
        .first()
    )


def latest_approved_verification_request(program: PartnerProgram, user=None):
    return (
        verification_requests_for_program(program, user=user)
        .select_related(
            "company",
            "initiator",
            "decided_by",
        )
        .prefetch_related("documents")
        .filter(status=PartnerProgramVerificationRequest.STATUS_APPROVED)
        .order_by("-decided_at", "-id")
        .first()
    )


def latest_verification_request_for_user(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None

    return (
        PartnerProgramVerificationRequest.objects.select_related(
            "program",
            "company",
            "initiator",
            "decided_by",
        )
        .prefetch_related("documents")
        .filter(initiator=user)
        .order_by("-submitted_at", "-id")
        .first()
    )


def apply_profile_verification_to_program(program: PartnerProgram, user) -> bool:
    latest_request = latest_verification_request_for_user(user)
    if not latest_request:
        return False

    program.verification_status = REQUEST_STATUS_TO_PROGRAM_STATUS.get(
        latest_request.status,
        PartnerProgram.VERIFICATION_STATUS_NOT_REQUESTED,
    )
    program.company = latest_request.company
    return True


def verification_requests_for_program(program: PartnerProgram, user=None):
    filters = Q(program=program)

    if program.company_id:
        filters |= Q(company_id=program.company_id)

    if user and getattr(user, "is_authenticated", False) and program.is_manager(user):
        filters |= Q(initiator=user)
    elif user is None:
        manager_ids = list(program.managers.values_list("id", flat=True))
        if manager_ids:
            filters |= Q(initiator_id__in=manager_ids)

    return PartnerProgramVerificationRequest.objects.filter(filters).distinct()


def _sync_profile_programs_verification_status(
    *,
    user,
    company,
    status_value: str,
    fallback_program: PartnerProgram,
) -> int:
    updates = {
        "verification_status": status_value,
        "company": company,
        "datetime_updated": timezone.now(),
    }

    if user and getattr(user, "is_authenticated", False):
        return PartnerProgram.objects.filter(managers=user).update(**updates)

    fallback_program.verification_status = status_value
    fallback_program.company = company
    fallback_program.save(
        update_fields=["verification_status", "company", "datetime_updated"]
    )
    return 1
