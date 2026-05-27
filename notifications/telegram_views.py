from __future__ import annotations

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import TelegramAccount
from notifications.telegram import (
    TelegramLinkError,
    bind_telegram_account,
    disconnect_telegram_account,
)


class TelegramWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not self._valid_secret(request):
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        reply = self.build_reply(request.data)
        if not reply:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        return Response(reply, status=status.HTTP_200_OK)

    def build_reply(self, update: dict) -> dict | None:
        message = update.get("message") or update.get("edited_message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        from_user = message.get("from") or {}
        chat_id = chat.get("id")

        if not text or chat_id is None:
            return None

        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()

        if command == "/start":
            reply_text = self._handle_start(
                raw_token=argument.strip(),
                chat_id=chat_id,
                username=from_user.get("username") or "",
            )
        elif command == "/status":
            reply_text = self._handle_status(chat_id)
        elif command == "/stop":
            reply_text = self._handle_stop(chat_id)
        elif command.startswith("/"):
            reply_text = (
                "Используйте /status для проверки привязки или /stop для отключения."
            )
        else:
            reply_text = self._bind_token(
                raw_token=text,
                chat_id=chat_id,
                username=from_user.get("username") or "",
            )

        return self._telegram_reply(chat_id=chat_id, text=reply_text)

    def _valid_secret(self, request) -> bool:
        expected_secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
        if not expected_secret:
            return True
        return (
            request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            == expected_secret
        )

    def _handle_start(self, *, raw_token: str, chat_id: int, username: str) -> str:
        if not raw_token:
            return (
                "Пришлите токен подключения из личного кабинета PROCOLLAB "
                "одним сообщением в этот чат."
            )

        return self._bind_token(
            raw_token=raw_token,
            chat_id=chat_id,
            username=username,
        )

    def _bind_token(self, *, raw_token: str, chat_id: int, username: str) -> str:
        try:
            bind_telegram_account(
                raw_token=raw_token.strip(),
                chat_id=chat_id,
                username=username,
            )
        except TelegramLinkError as exc:
            return str(exc)

        return (
            "Telegram подключен к вашему аккаунту PROCOLLAB. "
            "Теперь вам будут приходить уведомления."
        )

    def _handle_status(self, chat_id: int) -> str:
        connected = TelegramAccount.objects.filter(
            telegram_chat_id=chat_id,
            is_active=True,
        ).exists()
        if connected:
            return "Telegram подключен к PROCOLLAB."
        return "Telegram пока не подключен к PROCOLLAB."

    def _handle_stop(self, chat_id: int) -> str:
        account = (
            TelegramAccount.objects.select_related("user")
            .filter(telegram_chat_id=chat_id, is_active=True)
            .first()
        )
        if account:
            disconnect_telegram_account(account.user)
        return "Telegram-уведомления PROCOLLAB отключены."

    def _telegram_reply(self, *, chat_id: int, text: str) -> dict:
        return {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
