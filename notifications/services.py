from collections.abc import Iterable
from urllib.parse import urlsplit

from django.db import transaction

from notifications.models import Notification


def _validate_action_url(action_url: str | None) -> str | None:
    """Разрешает только внутренние маршруты office, сформированные backend-кодом."""
    if action_url is None:
        return None
    parsed = urlsplit(action_url)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or not parsed.path.startswith("/office/")
        or parsed.path.startswith("//")
        or "\\" in action_url
    ):
        raise ValueError("action_url должен быть относительным маршрутом /office/.")
    return action_url


def _notification_defaults(
    *,
    actor_id: int | None,
    notification_type: str,
    title: str,
    message: str,
    action_url: str | None,
) -> dict:
    try:
        category = Notification.TYPE_CATEGORY[notification_type]
    except KeyError as exc:
        raise ValueError("Неизвестный тип уведомления.") from exc
    return {
        "actor_id": actor_id,
        "type": notification_type,
        "category": category,
        "title": title,
        "message": message,
        "action_url": _validate_action_url(action_url),
    }


@transaction.atomic
def create_notification(
    *,
    recipient_id: int,
    actor_id: int | None,
    notification_type: str,
    title: str,
    message: str,
    action_url: str | None,
    event_key: str,
) -> Notification | None:
    """Создаёт одно идемпотентное уведомление внутри транзакции события."""
    if actor_id is not None and actor_id == recipient_id:
        return None
    notification, _created = Notification.objects.get_or_create(
        recipient_id=recipient_id,
        event_key=event_key,
        defaults=_notification_defaults(
            actor_id=actor_id,
            notification_type=notification_type,
            title=title,
            message=message,
            action_url=action_url,
        ),
    )
    return notification


@transaction.atomic
def create_notifications(
    *,
    recipient_ids: Iterable[int | None],
    actor_id: int | None,
    notification_type: str,
    title: str,
    message: str,
    action_url: str | None,
    event_key: str,
) -> list[Notification]:
    """Создаёт уведомления нескольким уникальным получателям одним INSERT."""
    recipients = sorted(
        {
            recipient_id
            for recipient_id in recipient_ids
            if recipient_id is not None and recipient_id != actor_id
        }
    )
    if not recipients:
        return []
    defaults = _notification_defaults(
        actor_id=actor_id,
        notification_type=notification_type,
        title=title,
        message=message,
        action_url=action_url,
    )
    notifications = [
        Notification(
            recipient_id=recipient_id,
            event_key=event_key,
            **defaults,
        )
        for recipient_id in recipients
    ]
    # UniqueConstraint остаётся окончательной защитой от retry и гонок.
    return Notification.objects.bulk_create(notifications, ignore_conflicts=True)
