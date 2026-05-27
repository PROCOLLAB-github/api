import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Register PROCOLLAB Telegram webhook."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default="",
            help="Full webhook URL. Defaults to SITE_URL/telegram/webhook/.",
        )

    def handle(self, *args, **options):
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise CommandError("TELEGRAM_BOT_TOKEN is not configured.")

        webhook_url = options["url"] or (
            f"{settings.SITE_URL.rstrip('/')}/telegram/webhook/"
        )
        payload = {"url": webhook_url}
        secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
        if secret:
            payload["secret_token"] = secret

        response = requests.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json=payload,
            timeout=10,
        )
        if response.status_code >= 400:
            raise CommandError(response.text)
        data = response.json()
        if not data.get("ok"):
            raise CommandError(response.text)
        self.stdout.write(self.style.SUCCESS(f"Telegram webhook set: {webhook_url}"))
