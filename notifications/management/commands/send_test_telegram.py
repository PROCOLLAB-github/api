from django.core.management.base import BaseCommand, CommandError

from notifications.telegram import send_telegram_message


class Command(BaseCommand):
    help = "Send a test Telegram message to a chat id."

    def add_arguments(self, parser):
        parser.add_argument("chat_id", type=int)
        parser.add_argument(
            "--message",
            default="Тестовое сообщение PROCOLLAB.",
        )

    def handle(self, *args, **options):
        try:
            message_id = send_telegram_message(
                chat_id=options["chat_id"],
                text=options["message"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Telegram message sent: {message_id or 'ok'}")
        )
