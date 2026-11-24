"""Личные уведомления администраторов и восстанавливаемая очередь писем."""

import logging
from functools import partial

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from partner_programs.models import (
    RegistrationConnectionEmail,
    RegistrationConnectionRequest,
    RegistrationConnectionNotification,
)
from partner_programs.services.management import person_name
from users.models import CustomUser

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 4


def is_administrator(user):
    return user.is_active and (user.is_staff or user.is_superuser)


def fanout_request(event, *, email_to_administrators):
    ids = []
    status = "queued" if email_to_administrators else "in_app_only"
    administrators = CustomUser.objects.filter(is_active=True).filter(
        Q(is_staff=True) | Q(is_superuser=True)
    )
    for recipient in administrators:
        notice, _ = RegistrationConnectionNotification.objects.get_or_create(
            request=event, recipient=recipient, defaults={"delivery_status": status}
        )
        if notice.delivery_status == "queued":
            ids.append(notice.pk)
    return ids


def queue_notifications(ids, *, direct_email=False):
    from partner_programs.tasks import (
        send_registration_connection_email,
        send_registration_connection_notification,
    )

    send = (
        send_registration_connection_email
        if direct_email
        else send_registration_connection_notification
    )
    for notification_id in ids:
        try:
            send.delay(notification_id)
        except Exception:
            # Запись остается queued; ее подберет периодическая задача.
            logger.exception(
                "Unable to enqueue %s %s", send.name, notification_id
            )


def record_request(config, user):
    event = RegistrationConnectionRequest.objects.create(
        registration=config,
        revision=config.revision,
        requested_by=user,
        requester_name=person_name(user),
        requester_email=user.email,
        website_url=config.connection_website_url,
        comment=config.connection_comment,
        contact=config.connection_contact,
        created_at=config.requested_at,
    )
    addresses = dict.fromkeys(
        address.lower()
        for address in settings.PROGRAM_REGISTRATION_REQUEST_EMAILS
        if address
    )
    notification_ids = fanout_request(event, email_to_administrators=not addresses)
    if notification_ids:
        transaction.on_commit(partial(queue_notifications, notification_ids), robust=True)
    if addresses:
        email_ids = [
            RegistrationConnectionEmail.objects.create(request=event, email=address).pk
            for address in addresses
        ]
        transaction.on_commit(
            partial(queue_notifications, email_ids, direct_email=True), robust=True
        )
    return event


def visible_request_notifications(user):
    rows = RegistrationConnectionNotification.objects.none()
    if is_administrator(user):
        rows = RegistrationConnectionNotification.objects.filter(recipient=user)
    return rows.select_related("request__registration__program").order_by(
        "-request__created_at", "-pk"
    )


def deliver_notification(notification_id, *, direct_email=False):
    model = (
        RegistrationConnectionEmail if direct_email else RegistrationConnectionNotification
    )
    related = ["request__registration__program"]
    if not direct_email:
        related.append("recipient")

    error = None
    # Блокировка и emailed_at защищают от параллельных повторов одной задачи.
    with transaction.atomic():
        notice = (
            model.objects.select_for_update(of=("self",))
            .select_related(*related)
            .filter(pk=notification_id)
            .first()
        )
        if (
            not notice
            or notice.emailed_at
            or notice.attempts >= MAX_ATTEMPTS
            or notice.delivery_status != "queued"
        ):
            return
        if not direct_email and not is_administrator(notice.recipient):
            notice.delivery_status = "cancelled"
            notice.save(update_fields=["delivery_status"])
            return
        address = notice.email if direct_email else notice.recipient.email
        if not address:
            notice.delivery_status = "failed"
            notice.attempts = MAX_ATTEMPTS
            notice.save(update_fields=["delivery_status", "attempts"])
            return
        event = notice.request
        context = {
            "program_name": event.registration.program.name,
            "website_url": event.website_url,
            "requester_name": event.requester_name,
            "requester_email": event.requester_email,
            "comment": event.comment,
            "contact": event.contact,
            "created_at": event.created_at,
            "admin_url": settings.EXPERT_WORKSPACE_FRONTEND_URL.rstrip("/")
            + reverse(
                "admin:partner_programs_programregistration_change",
                args=[event.registration_id],
            ),
        }
        notice.attempts += 1
        try:
            message = EmailMultiAlternatives(
                "Запрос на подключение сайта мероприятия | PROCOLLAB",
                render_to_string("email/registration_connection_request.txt", context),
                settings.EMAIL_USER,
                [address],
            )
            message.attach_alternative(
                render_to_string("email/registration_connection_request.html", context),
                "text/html",
            )
            if not message.send():
                raise RuntimeError("Registration request email delivery did not complete")
        except Exception as exc:
            error = exc
            notice.delivery_status = (
                "failed" if notice.attempts >= MAX_ATTEMPTS else "queued"
            )
        else:
            notice.delivery_status = "sent"
            notice.emailed_at = timezone.now()
        notice.save(update_fields=["attempts", "delivery_status", "emailed_at"])
    # Состояние не откатывается при запуске autoretry Celery.
    if error is not None:
        raise error


def pending_ids(model):
    return list(
        model.objects.filter(
            delivery_status="queued",
            emailed_at__isnull=True,
            attempts__lt=MAX_ATTEMPTS,
        )
        .order_by("pk")
        .values_list("pk", flat=True)[:100]
    )


def dispatch_pending_notifications():
    # Уведомление в колокольчике можно создать и после появления администратора.
    for event in RegistrationConnectionRequest.objects.filter(
        notifications__isnull=True
    ).order_by("pk")[:100]:
        fanout_request(
            event,
            email_to_administrators=(
                not settings.PROGRAM_REGISTRATION_REQUEST_EMAILS
                and not event.email_deliveries.exists()
            ),
        )
    notification_ids = pending_ids(RegistrationConnectionNotification)
    email_ids = pending_ids(RegistrationConnectionEmail)
    queue_notifications(notification_ids)
    queue_notifications(email_ids, direct_email=True)
    return len(notification_ids) + len(email_ids)
