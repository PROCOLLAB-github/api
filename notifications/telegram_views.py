from __future__ import annotations

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import TelegramAccount
from notifications.telegram import (
    TelegramLinkError,
    TelegramPermanentError,
    TelegramRetryableError,
    bind_telegram_account,
    disconnect_telegram_account,
    send_telegram_message,
)

logger = logging.getLogger(__name__)


class TelegramWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not self._valid_secret(request):
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        message = request.data.get("message") or request.data.get("edited_message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        from_user = message.get("from") or {}
        chat_id = chat.get("id")

        if not text or chat_id is None:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()

        if command == "/start":
            self._handle_start(
                raw_token=argument.strip(),
                chat_id=chat_id,
                username=from_user.get("username") or "",
            )
        elif command == "/status":
            self._handle_status(chat_id)
        elif command == "/stop":
            self._handle_stop(chat_id)
        else:
            self._safe_reply(
                chat_id,
                "Используйте /status для проверки привязки или /stop для отключения.",
            )

        return Response({"ok": True}, status=status.HTTP_200_OK)

    def _valid_secret(self, request) -> bool:
        expected_secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
        if not expected_secret:
            return True
        return (
            request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            == expected_secret
        )

    def _handle_start(self, *, raw_token: str, chat_id: int, username: str) -> None:
        if not raw_token:
            self._safe_reply(
                chat_id,
                "Откройте ссылку привязки из личного кабинета PROCOLLAB.",
            )
            return
        try:
            bind_telegram_account(
                raw_token=raw_token,
                chat_id=chat_id,
                username=username,
            )
        except TelegramLinkError as exc:
            self._safe_reply(chat_id, str(exc))
            return
        self._safe_reply(chat_id, "Telegram подключен к вашему аккаунту PROCOLLAB.")

    def _handle_status(self, chat_id: int) -> None:
        connected = TelegramAccount.objects.filter(
            telegram_chat_id=chat_id,
            is_active=True,
        ).exists()
        if connected:
            self._safe_reply(chat_id, "Telegram подключен к PROCOLLAB.")
        else:
            self._safe_reply(chat_id, "Telegram пока не подключен к PROCOLLAB.")

    def _handle_stop(self, chat_id: int) -> None:
        account = (
            TelegramAccount.objects.select_related("user")
            .filter(telegram_chat_id=chat_id, is_active=True)
            .first()
        )
        if account:
            disconnect_telegram_account(account.user)
        self._safe_reply(chat_id, "Telegram-уведомления PROCOLLAB отключены.")

    def _safe_reply(self, chat_id: int, text: str) -> None:
        try:
            send_telegram_message(chat_id=chat_id, text=text)
        except (TelegramPermanentError, TelegramRetryableError):
            logger.exception("Telegram webhook reply failed")
