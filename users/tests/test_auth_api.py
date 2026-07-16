import runpy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.constants import USER_CREATE_DATA
from users.models import CustomUser
from users.serializers import UserDetailSerializer

from .helpers import build_user


class UserRegistrationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("users.views.verify_email")
    def test_user_registration_creates_inactive_user_and_sends_email(self, verify_email_mock):
        response = self.client.post("/auth/users/", USER_CREATE_DATA, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], USER_CREATE_DATA["email"])
        self.assertEqual(response.data["is_active"], False)
        user = CustomUser.objects.get(email=USER_CREATE_DATA["email"])
        verify_email_mock.assert_called_once()
        self.assertEqual(verify_email_mock.call_args.args[0], user)

    @patch("users.views.verify_email")
    def test_user_registration_rejects_duplicate_email(self, _verify_email_mock):
        first_response = self.client.post("/auth/users/", USER_CREATE_DATA, format="json")
        second_response = self.client.post("/auth/users/", USER_CREATE_DATA, format="json")

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 400)

    def test_user_registration_rejects_invalid_payload(self):
        response = self.client.post(
            "/auth/users/",
            {
                "email": "wrong-email",
                "password": "qwe",
                "first_name": "И",
                "last_name": "Иванов",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    @patch(
        "django.core.mail.backends.console.EmailBackend.write_message",
        return_value=1,
    )
    def test_user_registration_works_with_console_email_backend(self, write_message_mock):
        response = self.client.post("/auth/users/", USER_CREATE_DATA, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], USER_CREATE_DATA["email"])
        self.assertEqual(response.data["is_active"], False)
        user = CustomUser.objects.get(email=USER_CREATE_DATA["email"])
        self.assertFalse(user.is_active)
        write_message_mock.assert_called_once()

    def test_token_obtain_pair_updates_last_login(self):
        user = build_user(email="login@example.com")

        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": user.email, "password": "very_strong_password"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)


class CurrentUserAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_current_user_returns_authenticated_user_profile(self):
        user = build_user(email="current@example.com")
        self.client.force_authenticate(user=user)

        response = self.client.get("/auth/users/current/")
        expected_data = UserDetailSerializer(
            user,
            context={"request": response.wsgi_request},
        ).data

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, expected_data)

    def test_removed_legacy_routes_return_404(self):
        self.assertEqual(self.client.get("/auth/users/clone-data").status_code, 404)
        self.assertEqual(self.client.get("/auth/subscription/").status_code, 404)
        self.assertEqual(self.client.post("/auth/subscription/buy/").status_code, 404)


class EmailSettingsDefaultsTests(SimpleTestCase):
    def test_email_settings_keep_existing_defaults_without_env(self):
        settings_path = Path(__file__).resolve().parents[2] / "procollab/settings.py"

        def return_default(_name, default=None, cast=None):
            return cast(default) if cast else default

        with patch("decouple.config", side_effect=return_default):
            loaded_settings = runpy.run_path(settings_path)

        self.assertEqual(
            loaded_settings["EMAIL_BACKEND"],
            "anymail.backends.unisender_go.EmailBackend",
        )
        self.assertEqual(
            loaded_settings["VERIFY_EMAIL_REDIRECT_URL"],
            "https://app.procollab.ru/auth/verification/",
        )


class VerifyEmailRedirectTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(
        VERIFY_EMAIL_REDIRECT_URL=("https://react-dev.procollab.ru/auth/verification")
    )
    def test_confirmation_handler_uses_configured_redirect(self):
        user = build_user(email="confirm@example.com", is_active=False)
        token = str(RefreshToken.for_user(user).access_token)

        response = self.client.get(
            "/auth/account-confirm-email/",
            {"token": token},
        )

        self.assertEqual(response.status_code, 302)
        redirect = urlparse(response["Location"])
        self.assertEqual(
            redirect._replace(query="", fragment="").geturl(),
            settings.VERIFY_EMAIL_REDIRECT_URL,
        )
        self.assertTrue(redirect.query.startswith("access_token="))
        self.assertIn("&refresh_token=", redirect.query)
