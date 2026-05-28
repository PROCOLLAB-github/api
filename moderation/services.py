from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from moderation.models import ModerationLog
from notifications.services import (
    notify_program_moderation_approved,
    notify_program_moderation_rejected,
    notify_program_submitted_to_moderation,
)
from partner_programs.models import PartnerProgram

AUTO_FREEZE_COMMENT = (
    "Чемпионат автоматически заморожен: обязательные материалы не были загружены "
    "после льготного периода от открытия регистрации."
)
FREEZE_GRACE_PERIOD_DAYS = 3


class ModerationTransitionError(Exception):
    def __init__(self, current_status: str):
        self.current_status = current_status
        super().__init__(current_status)


def create_moderation_log(
    *,
    program: PartnerProgram,
    author=None,
    action: str,
    status_before: str,
    status_after: str,
    comment: str = "",
    rejection_reason: str = "",
    sections_to_fix: list[str] | None = None,
) -> ModerationLog:
    return ModerationLog.objects.create(
        program=program,
        author=author if getattr(author, "is_authenticated", False) else None,
        action=action,
        status_before=status_before or "",
        status_after=status_after or "",
        comment=comment or "",
        rejection_reason=rejection_reason or "",
        sections_to_fix=sections_to_fix or [],
    )


def get_rejection_reasons() -> list[dict[str, str]]:
    return [
        {"code": code, "label": label}
        for code, label in ModerationLog.REJECTION_REASON_CHOICES
    ]


@transaction.atomic
def submit_program_to_moderation(
    program: PartnerProgram,
    *,
    author=None,
    comment: str = "",
) -> ModerationLog:
    status_before = program.status
    program.status = PartnerProgram.STATUS_PENDING_MODERATION
    program.draft = True
    program.save(update_fields=["status", "draft", "datetime_updated"])
    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_SUBMITTED,
        status_before=status_before,
        status_after=program.status,
        comment=comment,
    )
    notify_program_submitted_to_moderation(program, log)
    return log


@transaction.atomic
def approve_program(
    program: PartnerProgram,
    *,
    author,
    comment: str = "",
) -> ModerationLog:
    _require_pending_moderation(program)
    status_before = program.status
    program.status = PartnerProgram.STATUS_PUBLISHED
    program.draft = False
    program.save(update_fields=["status", "draft", "datetime_updated"])
    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_APPROVED,
        status_before=status_before,
        status_after=program.status,
        comment=comment,
    )
    notify_program_moderation_approved(program, log)
    return log


@transaction.atomic
def reject_program(
    program: PartnerProgram,
    *,
    author,
    comment: str,
    rejection_reason: str,
    sections_to_fix: list[str] | None = None,
) -> ModerationLog:
    _require_pending_moderation(program)
    if not comment or not comment.strip():
        raise ValidationError({"comment": "Комментарий обязателен при отклонении."})

    valid_reasons = {code for code, _ in ModerationLog.REJECTION_REASON_CHOICES}
    if rejection_reason not in valid_reasons:
        raise ValidationError({"rejection_reason": "Некорректная причина отклонения."})

    status_before = program.status
    program.status = PartnerProgram.STATUS_REJECTED
    program.draft = True
    program.save(update_fields=["status", "draft", "datetime_updated"])
    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_REJECTED,
        status_before=status_before,
        status_after=program.status,
        comment=comment,
        rejection_reason=rejection_reason,
        sections_to_fix=sections_to_fix,
    )
    notify_program_moderation_rejected(program, log)
    return log


@transaction.atomic
def withdraw_program_from_moderation(
    program: PartnerProgram,
    *,
    author,
    comment: str = "",
) -> ModerationLog:
    if program.status != PartnerProgram.STATUS_PENDING_MODERATION:
        raise ModerationTransitionError(program.status)

    status_before = program.status
    program.status = PartnerProgram.STATUS_DRAFT
    program.draft = True
    program.save(update_fields=["status", "draft", "datetime_updated"])
    return create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_WITHDRAWN,
        status_before=status_before,
        status_after=program.status,
        comment=comment,
    )


def can_freeze_program_automatically(program: PartnerProgram, *, now=None) -> bool:
    if now is None:
        now = timezone.now()
    if program.status != PartnerProgram.STATUS_PUBLISHED:
        return False
    if not program.datetime_started:
        return False
    if program.datetime_started >= now - timedelta(days=FREEZE_GRACE_PERIOD_DAYS):
        return False
    return not program.materials.exists()


@transaction.atomic
def freeze_program_automatically(
    program: PartnerProgram,
    *,
    now=None,
) -> ModerationLog | None:
    if now is None:
        now = timezone.now()
    if not can_freeze_program_automatically(program, now=now):
        return None

    status_before = program.status
    program.status = PartnerProgram.STATUS_FROZEN
    program.frozen_at = now
    program.draft = False
    program.save(update_fields=["status", "frozen_at", "draft", "datetime_updated"])
    log = create_moderation_log(
        program=program,
        author=None,
        action=ModerationLog.ACTION_AUTO_FREEZE,
        status_before=status_before,
        status_after=program.status,
        comment=AUTO_FREEZE_COMMENT,
    )
    send_freeze_notifications(program, log)
    return log


@transaction.atomic
def freeze_program_manually(
    program: PartnerProgram,
    *,
    author,
    comment: str,
    now=None,
) -> ModerationLog:
    if program.status != PartnerProgram.STATUS_PUBLISHED:
        raise ModerationTransitionError(program.status)
    if not comment or not comment.strip():
        raise ValidationError({"comment": "Комментарий обязателен при заморозке."})
    if now is None:
        now = timezone.now()

    status_before = program.status
    program.status = PartnerProgram.STATUS_FROZEN
    program.frozen_at = now
    program.draft = False
    program.save(update_fields=["status", "frozen_at", "draft", "datetime_updated"])
    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_FREEZE,
        status_before=status_before,
        status_after=program.status,
        comment=comment,
    )
    send_freeze_notifications(program, log)
    return log


@transaction.atomic
def restore_program(
    program: PartnerProgram,
    *,
    author,
    comment: str = "",
) -> ModerationLog:
    if program.status != PartnerProgram.STATUS_FROZEN:
        raise ModerationTransitionError(program.status)
    if not program.materials.exists():
        raise ValidationError(
            {"materials": "Materials are required before restoring a frozen program."}
        )

    status_before = program.status
    program.status = PartnerProgram.STATUS_PUBLISHED
    program.frozen_at = None
    program.draft = False
    program.save(update_fields=["status", "frozen_at", "draft", "datetime_updated"])
    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_RESTORE,
        status_before=status_before,
        status_after=program.status,
        comment=comment,
    )
    send_restore_notifications(program, log)
    return log


@transaction.atomic
def archive_program(
    program: PartnerProgram,
    *,
    author,
    comment: str = "",
) -> ModerationLog:
    if program.status not in (
        PartnerProgram.STATUS_FROZEN,
        PartnerProgram.STATUS_COMPLETED,
    ):
        raise ModerationTransitionError(program.status)
    if program.status == PartnerProgram.STATUS_FROZEN and not comment.strip():
        raise ValidationError(
            {"comment": "Комментарий обязателен при архивации замороженного чемпионата."}
        )

    status_before = program.status
    program.status = PartnerProgram.STATUS_ARCHIVED
    program.draft = False
    program.save(update_fields=["status", "draft", "datetime_updated"])
    log = create_moderation_log(
        program=program,
        author=author,
        action=ModerationLog.ACTION_ARCHIVE,
        status_before=status_before,
        status_after=program.status,
        comment=comment,
    )
    send_archive_notifications(program, log)
    return log


def _require_pending_moderation(program: PartnerProgram) -> None:
    if program.status != PartnerProgram.STATUS_PENDING_MODERATION:
        raise ModerationTransitionError(program.status)


def send_freeze_notifications(program: PartnerProgram, log: ModerationLog) -> int:
    reason = log.comment or AUTO_FREEZE_COMMENT
    sent_count = 0
    for manager in program.managers.all():
        if not _deadline_email_enabled(manager):
            continue
        sent_count += send_mail(
            subject=f'Program "{program.name}" was frozen',
            message=(
                f'Program "{program.name}" was frozen.\n\n'
                f"Reason:\n{reason}\n\n"
                f"Edit page: {_frontend_url()}/office/program/{program.id}/edit"
            ),
            from_email=_from_email(),
            recipient_list=[manager.email],
            fail_silently=True,
        )

    admin_emails = _admin_emails()
    if admin_emails:
        sent_count += send_mail(
            subject=f'Program "{program.name}" was frozen',
            message=(
                f'Program "{program.name}" (id={program.id}) was frozen.\n\n'
                f"Reason:\n{reason}\n\n"
                f"Moderation page: {_frontend_url()}/office/admin/moderation/programs/{program.id}"
            ),
            from_email=_from_email(),
            recipient_list=admin_emails,
            fail_silently=True,
        )
    return sent_count


def send_restore_notifications(program: PartnerProgram, log: ModerationLog) -> int:
    sent_count = 0
    for manager in program.managers.all():
        if not _moderation_email_enabled(manager):
            continue
        sent_count += send_mail(
            subject=f'Program "{program.name}" was restored',
            message=(
                f'Program "{program.name}" was restored and published again.\n\n'
                f"Program page: {_frontend_url()}/programs/{program.id}"
            ),
            from_email=_from_email(),
            recipient_list=[manager.email],
            fail_silently=True,
        )
    return sent_count


def send_archive_notifications(program: PartnerProgram, log: ModerationLog) -> int:
    sent_count = 0
    for manager in program.managers.all():
        if not _moderation_email_enabled(manager):
            continue
        sent_count += send_mail(
            subject=f'Program "{program.name}" was archived',
            message=(
                f'Program "{program.name}" was archived.\n\n'
                f"Moderator comment:\n{log.comment or 'No comment'}"
            ),
            from_email=_from_email(),
            recipient_list=[manager.email],
            fail_silently=True,
        )
    return sent_count


def _moderation_email_enabled(user) -> bool:
    try:
        return user.notification_preferences.email_moderation_results
    except ObjectDoesNotExist:
        return True


def _deadline_email_enabled(user) -> bool:
    try:
        return user.notification_preferences.email_deadline_warnings
    except ObjectDoesNotExist:
        return True


def _admin_emails() -> list[str]:
    User = get_user_model()
    return list(
        User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
    )


def _from_email() -> str:
    return (
        getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or getattr(settings, "EMAIL_USER", "")
        or "no-reply@example.com"
    )


def _frontend_url() -> str:
    return getattr(settings, "FRONTEND_URL", "").rstrip("/")
