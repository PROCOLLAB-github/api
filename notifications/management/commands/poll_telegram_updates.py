from __future__ import annotations

import time

import requests
from django.core.management.base import BaseCommand, CommandError

from notifications.telegram import (
    TelegramPermanentError,
    TelegramRetryableError,
    send_telegram_message,
    telegram_api_post,
)
from notifications.telegram_views import TelegramWebhookView


class Command(BaseCommand):
    help = (
        "Poll Telegram updates and process them through the same handler as the webhook. "
        "Useful when Telegram cannot reach the Selectel webhook directly."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one polling request and exit.")
        parser.add_argument("--timeout", type=int, default=25, help="Telegram long-poll timeout.")
        parser.add_argument("--limit", type=int, default=50, help="Max updates per request.")
        parser.add_argument("--sleep", type=float, default=1.0, help="Sleep between empty polls.")
        parser.add_argument(
            "--drop-pending",
            action="store_true",
            help="Drop pending Telegram updates when deleting the webhook.",
        )
        parser.add_argument(
            "--keep-webhook",
            action="store_true",
            help="Do not delete the current webhook before polling.",
        )

    def handle(self, *args, **options):
        timeout = max(1, int(options["timeout"]))
        limit = max(1, min(100, int(options["limit"])))
        offset = None
        handler = TelegramWebhookView()

        if not options["keep_webhook"]:
            self._delete_webhook(drop_pending=options["drop_pending"])

        self.stdout.write(self.style.SUCCESS("Telegram polling started."))

        while True:
            try:
                updates = self._get_updates(
                    offset=offset,
                    timeout=timeout,
                    limit=limit,
                )
            except (requests.RequestException, TelegramPermanentError) as exc:
                if options["once"]:
                    raise CommandError(str(exc)) from exc
                self.stderr.write(f"Telegram polling error: {exc}")
                time.sleep(max(1.0, float(options["sleep"])))
                continue

            for update in updates:
                update_id = update.get("update_id")
                if update_id is not None:
                    offset = max(offset or 0, int(update_id) + 1)
                self._process_update(handler, update)

            if options["once"]:
                break
            if not updates:
                time.sleep(max(0.1, float(options["sleep"])))

    def _delete_webhook(self, *, drop_pending: bool):
        response = telegram_api_post(
            "deleteWebhook",
            payload={"drop_pending_updates": drop_pending},
            timeout=10,
        )
        data = self._response_json(response)
        if response.status_code >= 400 or not data.get("ok"):
            raise CommandError(f"Unable to delete Telegram webhook: {response.text}")

    def _get_updates(self, *, offset: int | None, timeout: int, limit: int) -> list[dict]:
        payload = {
            "timeout": timeout,
            "limit": limit,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = telegram_api_post(
            "getUpdates",
            payload=payload,
            timeout=timeout + 10,
        )
        data = self._response_json(response)
        if response.status_code >= 400 or not data.get("ok"):
            raise CommandError(f"Unable to poll Telegram updates: {response.text}")
        return data.get("result", [])

    def _process_update(self, handler: TelegramWebhookView, update: dict):
        reply = handler.build_reply(update)
        if not reply or reply.get("method") != "sendMessage":
            return
        try:
            send_telegram_message(
                chat_id=reply["chat_id"],
                text=reply["text"],
                reply_markup=reply.get("reply_markup"),
            )
        except TelegramRetryableError as exc:
            self.stderr.write(f"Telegram reply retryable error: {exc}")
        except TelegramPermanentError as exc:
            self.stderr.write(f"Telegram reply permanent error: {exc}")

    def _response_json(self, response) -> dict:
        try:
            return response.json()
        except ValueError:
            return {}
