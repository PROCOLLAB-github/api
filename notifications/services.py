from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from notifications.models import Notification, NotificationDelivery
from notifications.tasks import send_notification_email, send_telegram_notification
from notifications.telegram import telegram_enabled_for_notification


EMAIL_TEMPLATES = {
    Notification.Type.PROGRAM_SUBMITTED_TO_MODERATION: "email/notifications/admin_program_submitted.html",
    Notification.Type.PROGRAM_MODERATION_APPROVED: "email/notifications/organizer_program_approved.html",
    Notification.Type.PROGRAM_MODERATION_REJECTED: "email/notifications/organizer_program_rejected.html",
    Notification.Type.COMPANY_VERIFICATION_SUBMITTED: "email/notifications/admin_verification_submitted.html",
    Notification.Type.COMPANY_VERIFICATION_APPROVED: "email/notifications/organizer_verification_approved.html",
    Notification.Type.COMPANY_VERIFICATION_REJECTED: "email/notifications/organizer_verification_rejected.html",
    Notification.Type.EXPERT_PROJECTS_ASSIGNED: "email/notifications/expert_projects_assigned.html",
}


EMAIL_SUBJECTS = {
    Notification.Type.PROGRAM_SUBMITTED_TO_MODERATION: "Новый чемпионат на модерации",
    Notification.Type.PROGRAM_MODERATION_APPROVED: "Кейс-чемпионат опубликован",
    Notification.Type.PROGRAM_MODERATION_REJECTED: "Кейс-чемпионат отправлен на доработку",
    Notification.Type.COMPANY_VERIFICATION_SUBMITTED: "Новая заявка на верификацию компании",
    Notification.Type.COMPANY_VERIFICATION_APPROVED: "Компания подтверждена в PROCOLLAB",
    Notification.Type.COMPANY_VERIFICATION_REJECTED: "Заявка на верификацию отклонена",
    Notification.Type.EXPERT_PROJECTS_ASSIGNED: "Вам назначены проекты для оценки",
}


EMAIL_PREFERENCE_FIELDS = {
    Notification.Type.PROGRAM_SUBMITTED_TO_MODERATION: "email_moderation_results",
    Notification.Type.PROGRAM_MODERATION_APPROVED: "email_moderation_results",
    Notification.Type.PROGRAM_MODERATION_REJECTED: "email_moderation_results",
    Notification.Type.COMPANY_VERIFICATION_SUBMITTED: "email_verification_results",
    Notification.Type.COMPANY_VERIFICATION_APPROVED: "email_verification_results",
    Notification.Type.COMPANY_VERIFICATION_REJECTED: "email_verification_results",
    Notification.Type.EXPERT_PROJECTS_ASSIGNED: "email_reminders_enabled",
}


def notify_program_submitted_to_moderation(program, log) -> int:
    url = f"/office/admin/moderation/programs/{program.id}"
    title = "Новый чемпионат ожидает проверки"
    message = f"«{program.name}» отправлен на модерацию"
    context = _base_context(
        title=title,
        message=message,
        program=program,
        url=url,
        cta_label="Проверить чемпионат",
        extra={
            "organizer_name": _program_organizer_name(program),
            "submitted_at": _format_datetime(getattr(log, "datetime_created", None)),
        },
    )
    return create_event_notifications(
        recipients=_staff_recipients(),
        notification_type=Notification.Type.PROGRAM_SUBMITTED_TO_MODERATION,
        title=title,
        message=message,
        object_type="moderation_log",
        object_id=log.id,
        url=url,
        dedupe_key=f"moderation:{log.id}:submitted",
        email_context=context,
    )


def notify_program_moderation_approved(program, log) -> int:
    url = f"/office/program/{program.id}"
    title = "Чемпионат опубликован"
    message = f"«{program.name}» прошел модерацию и появился на витрине"
    context = _base_context(
        title=title,
        message=message,
        program=program,
        url=url,
        cta_label="Открыть чемпионат",
    )
    return create_event_notifications(
        recipients=_program_manager_recipients(program),
        notification_type=Notification.Type.PROGRAM_MODERATION_APPROVED,
        title=title,
        message=message,
        object_type="moderation_log",
        object_id=log.id,
        url=url,
        dedupe_key=f"moderation:{log.id}:approved",
        email_context=context,
    )


def notify_program_moderation_rejected(program, log) -> int:
    url = f"/office/program/{program.id}/edit/main"
    title = "Чемпионат отправлен на доработку"
    message = f"Модератор оставил комментарий по чемпионату «{program.name}»"
    context = _base_context(
        title=title,
        message=message,
        program=program,
        url=url,
        cta_label="Перейти к редактированию",
        extra={
            "reason": _safe_display(log, "get_rejection_reason_display"),
            "comment": getattr(log, "comment", ""),
        },
    )
    return create_event_notifications(
        recipients=_program_manager_recipients(program),
        notification_type=Notification.Type.PROGRAM_MODERATION_REJECTED,
        title=title,
        message=message,
        object_type="moderation_log",
        object_id=log.id,
        url=url,
        dedupe_key=f"moderation:{log.id}:rejected",
        email_context=context,
    )


def notify_verification_submitted(program, verification_request) -> int:
    url = f"/office/admin/moderation/verification/{verification_request.id}"
    company_name = _verification_company_name(verification_request)
    title = "Новая заявка на верификацию"
    message = f"Компания «{company_name}» отправила заявку на подтверждение"
    context = _base_context(
        title=title,
        message=message,
        program=program,
        url=url,
        cta_label="Проверить заявку",
        extra={
            "company_name": company_name,
            "submitted_at": _format_datetime(
                getattr(verification_request, "submitted_at", None)
            ),
            "request_id": verification_request.id,
        },
    )
    return create_event_notifications(
        recipients=_staff_recipients(),
        notification_type=Notification.Type.COMPANY_VERIFICATION_SUBMITTED,
        title=title,
        message=message,
        object_type="verification_request",
        object_id=verification_request.id,
        url=url,
        dedupe_key=f"verification:{verification_request.id}:submitted",
        email_context=context,
    )


def notify_verification_approved(verification_request) -> int:
    program = verification_request.program
    url = f"/office/program/{program.id}/edit/verification"
    title = "Компания подтверждена"
    message = (
        f"Для чемпионата «{program.name}» теперь доступен бейдж "
        "«Официальная компания»"
    )
    context = _base_context(
        title=title,
        message=message,
        program=program,
        url=url,
        cta_label="Открыть чемпионат",
        extra={"company_name": _verification_company_name(verification_request)},
    )
    return create_event_notifications(
        recipients=_verification_result_recipients(verification_request),
        notification_type=Notification.Type.COMPANY_VERIFICATION_APPROVED,
        title=title,
        message=message,
        object_type="verification_request",
        object_id=verification_request.id,
        url=url,
        dedupe_key=f"verification:{verification_request.id}:approved",
        email_context=context,
    )


def notify_verification_rejected(verification_request) -> int:
    program = verification_request.program
    url = f"/office/program/{program.id}/edit/verification"
    title = "Заявка на верификацию отклонена"
    message = "Модератор оставил комментарий по заявке компании"
    context = _base_context(
        title=title,
        message=message,
        program=program,
        url=url,
        cta_label="Подать повторно",
        extra={
            "company_name": _verification_company_name(verification_request),
            "reason": _safe_display(
                verification_request,
                "get_rejection_reason_display",
            ),
            "comment": getattr(verification_request, "admin_comment", ""),
        },
    )
    return create_event_notifications(
        recipients=_verification_result_recipients(verification_request),
        notification_type=Notification.Type.COMPANY_VERIFICATION_REJECTED,
        title=title,
        message=message,
        object_type="verification_request",
        object_id=verification_request.id,
        url=url,
        dedupe_key=f"verification:{verification_request.id}:rejected",
        email_context=context,
    )


def notify_expert_projects_assigned(
    *,
    program,
    expert,
    project_count: int,
    batch_key: str,
    project_ids: Iterable[int] | None = None,
) -> int:
    user = getattr(expert, "user", None)
    if not user or project_count <= 0:
        return 0

    url = f"/office/program/{program.id}/projects-rating"
    title = "Вам назначены проекты для оценки"
    message = f"В чемпионате «{program.name}» вам назначено {project_count} проектов"
    context = _base_context(
        title=title,
        message=message,
        program=program,
        url=url,
        cta_label="Перейти к оценке",
        extra={
            "project_count": project_count,
            "evaluation_deadline": _format_datetime(
                getattr(program, "datetime_evaluation_ends", None)
            ),
            "project_ids": list(project_ids or []),
        },
    )
    return create_event_notifications(
        recipients=[user],
        notification_type=Notification.Type.EXPERT_PROJECTS_ASSIGNED,
        title=title,
        message=message,
        object_type="project_expert_assignment_batch",
        object_id=program.id,
        url=url,
        dedupe_key=f"expert_assignment:{batch_key}",
        email_context=context,
    )


def create_event_notifications(
    *,
    recipients: Iterable[Any],
    notification_type: str,
    title: str,
    message: str,
    object_type: str,
    object_id: int | None,
    url: str,
    dedupe_key: str,
    email_context: dict[str, Any],
) -> int:
    created_count = 0
    for recipient in _unique_users(recipients):
        if not _inapp_enabled(recipient):
            continue

        notification, created = Notification.objects.get_or_create(
            recipient=recipient,
            type=notification_type,
            dedupe_key=dedupe_key,
            defaults={
                "title": title,
                "message": message,
                "object_type": object_type,
                "object_id": object_id,
                "url": url,
            },
        )
        if not created:
            continue

        created_count += 1
        NotificationDelivery.objects.create(
            notification=notification,
            channel=NotificationDelivery.Channel.IN_APP,
            status=NotificationDelivery.Status.SENT,
            sent_at=timezone.now(),
        )
        if _email_enabled(recipient, notification_type):
            _create_email_delivery(notification, notification_type, email_context)
        if telegram_enabled_for_notification(notification):
            _create_telegram_delivery(notification)

    return created_count


def _create_email_delivery(
    notification: Notification,
    notification_type: str,
    context: dict[str, Any],
) -> NotificationDelivery:
    delivery = NotificationDelivery.objects.create(
        notification=notification,
        channel=NotificationDelivery.Channel.EMAIL,
        status=NotificationDelivery.Status.PENDING,
    )
    subject = EMAIL_SUBJECTS[notification_type]
    template_name = EMAIL_TEMPLATES[notification_type]
    plain_text = _plain_text_message(context)

    def enqueue_email() -> None:
        send_notification_email.delay(
            delivery.id,
            subject,
            template_name,
            context,
            plain_text,
        )

    transaction.on_commit(enqueue_email)
    return delivery


def _create_telegram_delivery(notification: Notification) -> NotificationDelivery:
    delivery = NotificationDelivery.objects.create(
        notification=notification,
        channel=NotificationDelivery.Channel.TELEGRAM,
        status=NotificationDelivery.Status.PENDING,
    )

    def enqueue_telegram() -> None:
        send_telegram_notification.delay(delivery.id)

    transaction.on_commit(enqueue_telegram)
    return delivery


def _plain_text_message(context: dict[str, Any]) -> str:
    lines = [
        "Здравствуйте!",
        "",
        str(context.get("message") or context.get("title") or ""),
    ]
    for key, label in (
        ("program_title", "Чемпионат"),
        ("company_name", "Компания"),
        ("project_count", "Количество проектов"),
        ("evaluation_deadline", "Дедлайн оценки"),
        ("reason", "Причина"),
        ("comment", "Комментарий"),
    ):
        value = context.get(key)
        if value:
            lines.extend(["", f"{label}: {value}"])

    cta_url = context.get("cta_url")
    cta_label = context.get("cta_label") or "Открыть"
    if cta_url:
        lines.extend(["", f"{cta_label}: {cta_url}"])

    lines.extend(["", "Это автоматическое письмо PROCOLLAB."])
    return "\n".join(lines)


def _base_context(
    *,
    title: str,
    message: str,
    program,
    url: str,
    cta_label: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = {
        "title": title,
        "message": message,
        "program_id": program.id,
        "program_title": program.name,
        "cta_label": cta_label,
        "cta_url": _absolute_frontend_url(url),
        "relative_url": url,
    }
    if extra:
        context.update(extra)
    return context


def _absolute_frontend_url(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    base_url = (
        getattr(settings, "FRONTEND_URL", "")
        or getattr(settings, "SITE_URL", "")
        or "https://procollab.ru"
    )
    return f"{base_url.rstrip('/')}/{url.lstrip('/')}"


def _staff_recipients():
    User = get_user_model()
    return User.objects.filter(is_active=True, is_staff=True)


def _program_manager_recipients(program, extra_users: Iterable[Any] | None = None) -> list:
    recipients = list(program.managers.all())
    if extra_users:
        recipients.extend(extra_users)
    return _unique_users(recipients)


def _verification_result_recipients(verification_request) -> list:
    initiator = getattr(verification_request, "initiator", None)
    return _program_manager_recipients(
        verification_request.program,
        extra_users=[initiator] if initiator else None,
    )


def _unique_users(users: Iterable[Any]) -> list:
    seen = set()
    result = []
    for user in users:
        user_id = getattr(user, "id", None)
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        result.append(user)
    return result


def _inapp_enabled(user) -> bool:
    try:
        return user.notification_preferences.inapp_notifications_enabled
    except ObjectDoesNotExist:
        return True


def _email_enabled(user, notification_type: str) -> bool:
    if not getattr(user, "email", ""):
        return False
    preference_field = EMAIL_PREFERENCE_FIELDS.get(notification_type)
    if not preference_field:
        return True
    try:
        return bool(getattr(user.notification_preferences, preference_field))
    except ObjectDoesNotExist:
        return True


def _program_organizer_name(program) -> str:
    manager = program.managers.order_by("id").first()
    if not manager:
        return ""
    full_name = f"{manager.first_name} {manager.last_name}".strip()
    return full_name or manager.email


def _verification_company_name(verification_request) -> str:
    return (
        verification_request.company_name
        or getattr(verification_request.company, "name", "")
        or "Компания"
    )


def _format_datetime(value) -> str:
    if not value:
        return ""
    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def _safe_display(obj, method_name: str) -> str:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return ""
    try:
        value = method()
    except Exception:
        return ""
    return value or ""
