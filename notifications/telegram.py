from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from notifications.models import (
    Notification,
    NotificationChannelPreference,
    TelegramAccount,
    TelegramLinkToken,
)


TELEGRAM_LINK_TTL_MINUTES = 15
TELEGRAM_API_BASE_URL = "https://api.telegram.org/bot"

TELEGRAM_NOTIFICATION_TEXTS = {
    Notification.Type.PROGRAM_SUBMITTED_TO_MODERATION: (
        "Новый чемпионат отправлен на модерацию."
    ),
    Notification.Type.PROGRAM_MODERATION_APPROVED: "Кейс-чемпионат опубликован.",
    Notification.Type.PROGRAM_MODERATION_REJECTED: (
        "Кейс-чемпионат отправлен на доработку."
    ),
    Notification.Type.COMPANY_VERIFICATION_SUBMITTED: (
        "Новая заявка на верификацию компании ожидает проверки."
    ),
    Notification.Type.COMPANY_VERIFICATION_APPROVED: "Компания подтверждена.",
    Notification.Type.COMPANY_VERIFICATION_REJECTED: (
        "Заявка на верификацию компании отклонена."
    ),
    Notification.Type.EXPERT_PROJECTS_ASSIGNED: (
        "Вам назначены проекты для экспертной оценки."
    ),
}


class TelegramLinkError(Exception):
    pass


class TelegramRetryableError(Exception):
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class TelegramPermanentError(Exception):
    pass


@dataclass(frozen=True)
class TelegramLink:
    url: str
    token: str
    expires_at: Any


def token_hash(token: str) -> str:
    return salted_hmac("telegram-link-token", token).hexdigest()


def create_telegram_link(user) -> TelegramLink:
    bot_username = _bot_username()
    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(minutes=TELEGRAM_LINK_TTL_MINUTES)
    TelegramLinkToken.objects.create(
        user=user,
        token_hash=token_hash(token),
        expires_at=expires_at,
    )
    return TelegramLink(
        url=f"https://t.me/{bot_username}?start={token}",
        token=token,
        expires_at=expires_at,
    )


def bind_telegram_account(*, raw_token: str, chat_id: int, username: str = ""):
    now = timezone.now()
    with transaction.atomic():
        link_token = (
            TelegramLinkToken.objects.select_for_update()
            .select_related("user")
            .filter(
                token_hash=token_hash(raw_token),
                used_at__isnull=True,
                expires_at__gte=now,
            )
            .first()
        )
        if not link_token:
            raise TelegramLinkError("Ссылка привязки недействительна или устарела.")

        account, _ = TelegramAccount.objects.select_for_update().get_or_create(
            user=link_token.user
        )
        account.telegram_chat_id = chat_id
        account.telegram_username = username or ""
        account.is_active = True
        account.linked_at = now
        account.save(
            update_fields=[
                "telegram_chat_id",
                "telegram_username",
                "is_active",
                "linked_at",
                "datetime_updated",
            ]
        )

        link_token.used_at = now
        link_token.save(update_fields=["used_at"])
        set_all_telegram_preferences(link_token.user, enabled=True)
    return link_token.user


def disconnect_telegram_account(user) -> None:
    TelegramAccount.objects.filter(user=user).update(
        telegram_chat_id=None,
        telegram_username="",
        is_active=False,
        linked_at=None,
        datetime_updated=timezone.now(),
    )
    set_all_telegram_preferences(user, enabled=False)


def set_all_telegram_preferences(user, *, enabled: bool) -> None:
    for event_type in Notification.Type.values:
        NotificationChannelPreference.objects.update_or_create(
            user=user,
            channel=NotificationChannelPreference.Channel.TELEGRAM,
            event_type=event_type,
            defaults={"enabled": enabled},
        )


def get_telegram_preferences(user) -> dict[str, bool]:
    existing = {
        preference.event_type: preference.enabled
        for preference in NotificationChannelPreference.objects.filter(
            user=user,
            channel=NotificationChannelPreference.Channel.TELEGRAM,
        )
    }
    return {
        event_type: existing.get(event_type, True)
        for event_type in Notification.Type.values
    }


def update_telegram_preferences(user, values: dict[str, bool]) -> dict[str, bool]:
    allowed_types = set(Notification.Type.values)
    for event_type, enabled in values.items():
        if event_type not in allowed_types:
            continue
        NotificationChannelPreference.objects.update_or_create(
            user=user,
            channel=NotificationChannelPreference.Channel.TELEGRAM,
            event_type=event_type,
            defaults={"enabled": bool(enabled)},
        )
    return get_telegram_preferences(user)


def telegram_enabled_for_notification(notification: Notification) -> bool:
    if not getattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", False):
        return False
    try:
        account = notification.recipient.telegram_account
    except TelegramAccount.DoesNotExist:
        return False
    if not account.is_active or not account.telegram_chat_id:
        return False

    preference = NotificationChannelPreference.objects.filter(
        user=notification.recipient,
        channel=NotificationChannelPreference.Channel.TELEGRAM,
        event_type=notification.type,
    ).first()
    return True if preference is None else preference.enabled


def build_telegram_payload(notification: Notification) -> dict[str, Any]:
    text = TELEGRAM_NOTIFICATION_TEXTS.get(
        notification.type,
        "Новое уведомление PROCOLLAB.",
    )
    cta_url = _absolute_frontend_url(notification.url)
    payload = {"text": text}
    if cta_url:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [
                    {
                        "text": "Открыть в PROCOLLAB",
                        "url": cta_url,
                    }
                ]
            ]
        }
    return payload


def send_telegram_message(*, chat_id: int, text: str, reply_markup=None) -> str:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise TelegramPermanentError("TELEGRAM_BOT_TOKEN is not configured")

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(
            f"{TELEGRAM_API_BASE_URL}{token}/sendMessage",
            json=payload,
            timeout=10,
            proxies=telegram_proxies(),
        )
    except requests.RequestException as exc:
        raise TelegramRetryableError(str(exc)) from exc

    data = _safe_json(response)
    if response.status_code == 429:
        retry_after = _retry_after(data)
        raise TelegramRetryableError(
            f"Telegram API rate limit: {response.text}",
            retry_after=retry_after,
        )
    if response.status_code >= 500:
        raise TelegramRetryableError(f"Telegram API error: {response.text}")
    if response.status_code >= 400:
        raise TelegramPermanentError(f"Telegram API error: {response.text}")
    if not data.get("ok"):
        raise TelegramPermanentError(f"Telegram API rejected message: {response.text}")
    message_id = data.get("result", {}).get("message_id")
    return str(message_id or "")


def telegram_api_post(method: str, *, payload: dict[str, Any] | None = None, timeout: int = 10):
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise TelegramPermanentError("TELEGRAM_BOT_TOKEN is not configured")
    return requests.post(
        f"{TELEGRAM_API_BASE_URL}{token}/{method}",
        json=payload or {},
        timeout=timeout,
        proxies=telegram_proxies(),
    )


def telegram_proxies() -> dict[str, str] | None:
    proxy_url = getattr(settings, "TELEGRAM_PROXY_URL", "").strip()
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def _bot_username() -> str:
    username = getattr(settings, "TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    if not username:
        raise ImproperlyConfigured("TELEGRAM_BOT_USERNAME must be configured.")
    return username


def _absolute_frontend_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    base_url = (
        getattr(settings, "FRONTEND_URL", "")
        or getattr(settings, "SITE_URL", "")
        or ""
    )
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/{url.lstrip('/')}"


def _safe_json(response) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {}


def _retry_after(data: dict[str, Any]) -> int | None:
    try:
        return int(data.get("parameters", {}).get("retry_after"))
    except (TypeError, ValueError):
        return None
