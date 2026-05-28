from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string

from core.email import get_default_from_email, send_html_email


class Command(BaseCommand):
    help = (
        "Send a test email through the configured Django email backend. "
        "Use this after setting EMAIL_BACKEND and Unisender Go env variables."
    )

    def add_arguments(self, parser):
        parser.add_argument("to_email", help="Recipient email address")
        parser.add_argument(
            "--template",
            choices=("system", "registration"),
            default="system",
            help="Template to render for the test message",
        )

    def handle(self, *args, **options):
        to_email = options["to_email"]
        from_email = get_default_from_email()
        if not from_email:
            raise CommandError("DEFAULT_FROM_EMAIL or EMAIL_USER must be configured")

        context = {
            "email_backend": settings.EMAIL_BACKEND,
            "from_email": from_email,
            "absolute_url": getattr(settings, "SITE_URL", ""),
            "confirm_url": getattr(settings, "SITE_URL", ""),
            "frontend_url": getattr(settings, "FRONTEND_URL", ""),
        }

        if options["template"] == "registration":
            subject = "PROCOLLAB | Тест письма подтверждения"
            html_template = "email/confirm-email.html"
            text_template = "email/confirm-email.txt"
        else:
            subject = "PROCOLLAB | Тестовая отправка"
            html_template = "email/system-test.html"
            text_template = "email/system-test.txt"

        sent_count = send_html_email(
            subject=subject,
            to=[to_email],
            html_body=render_to_string(html_template, context),
            text_body=render_to_string(text_template, context),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {sent_count} message(s) using {settings.EMAIL_BACKEND}"
            )
        )
