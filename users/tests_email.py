from datetime import date
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from users.helpers import verify_email
from users.models import CustomUser


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="PROCOLLAB <sender@example.com>",
    EMAIL_USER="legacy@example.com",
    SITE_URL="https://procollab.pro",
    FRONTEND_URL="https://procollab.pro",
    VERIFY_EMAIL_REDIRECT_URL="https://procollab.pro/auth/verification/",
)
class TransactionalEmailTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="new.user@example.com",
            password="Password123",
            first_name="Иван",
            last_name="Петров",
            birthday=date(2000, 1, 1),
        )

    def test_verify_email_uses_default_sender_and_site_url(self):
        verify_email(self.user, request=None)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "PROCOLLAB <sender@example.com>")
        self.assertEqual(message.to, ["new.user@example.com"])
        self.assertIn("PROCOLLAB | Подтверждение почты", message.subject)
        self.assertIn("https://procollab.pro/", message.body)
        self.assertIn("token=", message.body)
        self.assertTrue(message.alternatives)
        self.assertIn("text/html", message.alternatives[0])

    def test_send_test_email_command_uses_active_backend(self):
        stdout = StringIO()

        call_command(
            "send_test_email",
            "owner@example.com",
            "--template",
            "registration",
            stdout=stdout,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, "PROCOLLAB <sender@example.com>")
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])
        self.assertIn("Sent 1 message", stdout.getvalue())
