from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .helpers import build_user


class UserCVAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = build_user(email="cv@example.com")
        self.client.force_authenticate(user=self.user)

    @patch("users.views.HTML")
    @patch("users.views.render_to_string", return_value="<html>cv</html>")
    @patch("users.views.UserCVDataPreparerV2")
    def test_user_can_download_cv_pdf(
        self,
        data_preparer_mock,
        _render_to_string_mock,
        html_mock,
    ):
        preparer = MagicMock()
        preparer.TEMPLATE_PATH = "template.html"
        preparer.get_prepared_data.return_value = {"base_user_info": self.user}
        data_preparer_mock.return_value = preparer
        html_mock.return_value.write_pdf.return_value = b"pdf"

        response = self.client.get("/auth/users/download_cv/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.content, b"pdf")

    @patch("users.views.HTML")
    @patch("users.views.render_to_string", return_value="<html>cv</html>")
    @patch("users.views.UserCVDataPreparerV2")
    def test_cv_download_has_cooldown(
        self,
        data_preparer_mock,
        _render_to_string_mock,
        html_mock,
    ):
        preparer = MagicMock()
        preparer.TEMPLATE_PATH = "template.html"
        preparer.get_prepared_data.return_value = {"base_user_info": self.user}
        data_preparer_mock.return_value = preparer
        html_mock.return_value.write_pdf.return_value = b"pdf"

        first_response = self.client.get("/auth/users/download_cv/")
        second_response = self.client.get("/auth/users/download_cv/")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)
        self.assertIn("seconds_after_retry", second_response.data)

    @patch("users.views.send_mail_cv.delay")
    def test_user_can_schedule_cv_email(self, delay_mock):
        response = self.client.get("/auth/users/send_mail_cv/")

        self.assertEqual(response.status_code, 200)
        delay_mock.assert_called_once_with(
            user_id=self.user.id,
            user_email=self.user.email,
            filename=f"{self.user.first_name}_{self.user.last_name}",
        )

    @patch("users.views.send_mail_cv.delay")
    def test_cv_email_has_cooldown(self, delay_mock):
        first_response = self.client.get("/auth/users/send_mail_cv/")
        second_response = self.client.get("/auth/users/send_mail_cv/")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(delay_mock.call_count, 1)
