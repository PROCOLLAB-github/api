"""Exercise the real PDF engine used by production CV downloads and email."""

from unittest.mock import patch

from django.core.cache import cache
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.tasks import send_mail_cv
from users.tests.helpers import build_user


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NativeCVPDFTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = build_user(
            email="native-cv@example.invalid",
            first_name="Александра",
            last_name="Добровольская",
            avatar="",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.network = patch(
            "core.services.Base64ImageEncoder.get_encoded_base64_from_url",
            side_effect=AssertionError("Synthetic CV must use only bundled assets"),
        )
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_download_uses_real_template_fonts_and_pdf_engine(self):
        response = self.client.get("/auth/users/download_cv/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 5000)

    def test_email_task_attaches_real_pdf_without_external_delivery(self):
        send_mail_cv.run(self.user.pk, self.user.email, "synthetic-cv")
        self.assertEqual(len(mail.outbox), 1)
        attachment = mail.outbox[0].attachments[0]
        self.assertEqual(attachment.filename, "synthetic-cv.pdf")
        self.assertEqual(attachment.mimetype, "application/pdf")
        self.assertTrue(attachment.content.startswith(b"%PDF"))
        self.assertGreater(len(attachment.content), 5000)
