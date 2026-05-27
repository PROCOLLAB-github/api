import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils import timezone

from notifications.models import NotificationDelivery
from notifications.telegram import (
    TelegramPermanentError,
    TelegramRetryableError,
    build_telegram_payload,
    send_telegram_message,
)
from procollab.celery import app

logger = logging.getLogger(__name__)


@app.task(name="notifications.tasks.send_notification_email")
def send_notification_email(
    delivery_id: int,
    subject: str,
    template_name: str,
    context: dict,
    plain_text: str,
) -> bool:
    try:
        delivery = NotificationDelivery.objects.select_related(
            "notification__recipient"
        ).get(pk=delivery_id)
    except NotificationDelivery.DoesNotExist:
        logger.warning("NotificationDelivery %s does not exist", delivery_id)
        return False

    if delivery.status == NotificationDelivery.Status.SENT:
        return True

    recipient = delivery.notification.recipient
    if not recipient.email:
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.error = "recipient email is empty"
        delivery.save(update_fields=["status", "error"])
        return False

    html_message = None
    try:
        html_message = render_to_string(template_name, context)
    except TemplateDoesNotExist:
        logger.warning("Email template %s is missing; using plain text", template_name)
    except Exception as exc:
        logger.exception("Email template %s render failed", template_name)
        delivery.error = f"html render failed; plain text fallback used: {exc}"

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=plain_text,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_USER),
            to=[recipient.email],
        )
        if html_message:
            message.attach_alternative(html_message, "text/html")
        sent_count = message.send(fail_silently=False)
    except Exception as exc:
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.error = str(exc)
        delivery.save(update_fields=["status", "error"])
        logger.exception("Notification email delivery %s failed", delivery_id)
        return False

    if sent_count:
        delivery.status = NotificationDelivery.Status.SENT
        delivery.sent_at = timezone.now()
        delivery.error = delivery.error or ""
        delivery.save(update_fields=["status", "sent_at", "error"])
        return True

    delivery.status = NotificationDelivery.Status.FAILED
    delivery.error = "email backend returned 0 sent messages"
    delivery.save(update_fields=["status", "error"])
    return False


@app.task(bind=True, name="notifications.tasks.send_telegram_notification", max_retries=3)
def send_telegram_notification(self, delivery_id: int) -> bool:
    try:
        delivery = NotificationDelivery.objects.select_related(
            "notification__recipient__telegram_account"
        ).get(pk=delivery_id)
    except NotificationDelivery.DoesNotExist:
        logger.warning("NotificationDelivery %s does not exist", delivery_id)
        return False

    if delivery.status == NotificationDelivery.Status.SENT:
        return True

    if delivery.channel != NotificationDelivery.Channel.TELEGRAM:
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.last_error = "delivery channel is not telegram"
        delivery.error = delivery.last_error
        delivery.save(update_fields=["status", "last_error", "error"])
        return False

    try:
        account = delivery.notification.recipient.telegram_account
    except Exception:
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.last_error = "telegram account is not linked"
        delivery.error = delivery.last_error
        delivery.save(update_fields=["status", "last_error", "error"])
        return False

    if not account.is_active or not account.telegram_chat_id:
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.last_error = "telegram account is disabled"
        delivery.error = delivery.last_error
        delivery.save(update_fields=["status", "last_error", "error"])
        return False

    delivery.attempts += 1
    delivery.save(update_fields=["attempts"])

    payload = build_telegram_payload(delivery.notification)
    try:
        provider_message_id = send_telegram_message(
            chat_id=account.telegram_chat_id,
            text=payload["text"],
            reply_markup=payload.get("reply_markup"),
        )
    except TelegramRetryableError as exc:
        delivery.last_error = str(exc)
        delivery.error = str(exc)
        delivery.save(update_fields=["last_error", "error"])
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=exc.retry_after or 60, exc=exc)
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.save(update_fields=["status"])
        logger.exception("Telegram delivery %s failed after retries", delivery_id)
        return False
    except TelegramPermanentError as exc:
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.last_error = str(exc)
        delivery.error = str(exc)
        delivery.save(update_fields=["status", "last_error", "error"])
        logger.warning("Telegram delivery %s permanently failed: %s", delivery_id, exc)
        return False

    delivery.status = NotificationDelivery.Status.SENT
    delivery.sent_at = timezone.now()
    delivery.provider_message_id = provider_message_id
    delivery.last_error = ""
    delivery.error = ""
    delivery.save(
        update_fields=[
            "status",
            "sent_at",
            "provider_message_id",
            "last_error",
            "error",
        ]
    )
    return True
