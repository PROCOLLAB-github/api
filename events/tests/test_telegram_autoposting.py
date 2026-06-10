from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from events.helpers import edit_message, send_message
from events.models import Event
from events.tests.helpers import build_event


class TelegramHelpersTests(TestCase):
    @override_settings(TELEGRAM_BOT_TOKEN="bot-token")
    @patch("events.helpers.requests.post")
    def test_send_message_uses_telegram_bot_api(self, post_mock):
        post_mock.return_value = Mock(json=Mock(return_value={"ok": True}))

        response = send_message("Текст", "@channel")

        self.assertEqual(response, {"ok": True})
        post_mock.assert_called_once_with(
            "https://api.telegram.org/botbot-token/sendMessage",
            data={
                "chat_id": "@channel",
                "text": "Текст",
                "parse_mode": "markdown",
            },
        )

    @override_settings(TELEGRAM_BOT_TOKEN="bot-token")
    @patch("events.helpers.requests.post")
    def test_edit_message_uses_telegram_bot_api(self, post_mock):
        post_mock.return_value = Mock(json=Mock(return_value={"ok": True}))

        response = edit_message("Новый текст", 123, "@channel")

        self.assertEqual(response, {"ok": True})
        post_mock.assert_called_once_with(
            "https://api.telegram.org/botbot-token/editMessageText",
            data={
                "chat_id": "@channel",
                "text": "Новый текст",
                "parse_mode": "markdown",
                "message_id": 123,
            },
        )


class EventAutopostingSignalTests(TestCase):
    def test_created_event_sends_telegram_message_and_stores_message_id(self):
        event = build_event(title="Telegram event", short_text="Short")
        from events.signals import autoposting_receiver

        with override_settings(AUTOPOSTING_ON=True, TELEGRAM_CHANNEL="@channel"):
            with patch(
                "events.signals.send_message",
                return_value={"ok": True, "result": {"message_id": 123}},
            ) as send_mock, patch("events.signals.edit_message"):
                autoposting_receiver(Event, event, True)

        event.refresh_from_db()
        self.assertEqual(event.tg_message_id, 123)
        send_mock.assert_called_once_with(
            "***Telegram event***\nShort\n\nhttps://procollab.ru/events/"
            f"{event.pk}",
            "@channel",
        )

    def test_updated_event_edits_existing_telegram_message(self):
        event = build_event(title="Updated event", short_text="New short")
        event.tg_message_id = 456
        event.save(update_fields=["tg_message_id"])
        from events.signals import autoposting_receiver

        with override_settings(AUTOPOSTING_ON=True, TELEGRAM_CHANNEL="@channel"):
            with patch("events.signals.edit_message") as edit_mock:
                autoposting_receiver(Event, event, False)

        edit_mock.assert_called_once_with(
            "***Updated event***\nNew short\n\nhttps://procollab.ru/events/"
            f"{event.pk}",
            456,
            "@channel",
        )

    def test_autoposting_disabled_does_not_call_telegram(self):
        event = build_event()
        from events.signals import autoposting_receiver

        with override_settings(AUTOPOSTING_ON=False):
            with patch("events.signals.send_message") as send_mock, patch(
                "events.signals.edit_message"
            ) as edit_mock:
                autoposting_receiver(Event, event, True)

        send_mock.assert_not_called()
        edit_mock.assert_not_called()
