from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from tests.constants import USER_CREATE_DATA
from users.tests.helpers import build_user


def throttle_settings(**rates):
    rest_framework = dict(settings.REST_FRAMEWORK)
    rest_framework["DEFAULT_THROTTLE_RATES"] = {
        **rest_framework.get("DEFAULT_THROTTLE_RATES", {}),
        **rates,
    }
    return rest_framework


class AuthThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    @override_settings(
        REST_FRAMEWORK=throttle_settings(auth_register="1/min")
    )
    @patch("users.views.verify_email")
    def test_user_registration_post_is_scoped_throttled(self, verify_email_mock):
        first_response = self.client.post(
            "/auth/users/",
            USER_CREATE_DATA,
            format="json",
            REMOTE_ADDR="203.0.113.10",
        )
        second_payload = {
            **USER_CREATE_DATA,
            "email": "second-user@example.com",
        }
        second_response = self.client.post(
            "/auth/users/",
            second_payload,
            format="json",
            REMOTE_ADDR="203.0.113.10",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 429)
        verify_email_mock.assert_called_once()

    @override_settings(
        REST_FRAMEWORK=throttle_settings(auth_resend_email="1/min")
    )
    @patch("users.views.verify_email")
    def test_resend_verify_email_post_is_scoped_throttled(self, verify_email_mock):
        user = build_user(email="inactive-throttle@example.com", is_active=False)

        first_response = self.client.post(
            "/auth/resend_email/",
            {"email": user.email},
            format="json",
            REMOTE_ADDR="203.0.113.11",
        )
        second_response = self.client.post(
            "/auth/resend_email/",
            {"email": user.email},
            format="json",
            REMOTE_ADDR="203.0.113.11",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 429)
        verify_email_mock.assert_called_once()

    @override_settings(
        REST_FRAMEWORK=throttle_settings(token_obtain="1/min")
    )
    def test_token_obtain_post_is_scoped_throttled(self):
        user = build_user(email="token-throttle@example.com")
        payload = {"email": user.email, "password": "very_strong_password"}

        first_response = self.client.post(
            "/api/token/",
            payload,
            format="json",
            REMOTE_ADDR="203.0.113.12",
        )
        second_response = self.client.post(
            "/api/token/",
            payload,
            format="json",
            REMOTE_ADDR="203.0.113.12",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 429)

    @override_settings(
        REST_FRAMEWORK=throttle_settings(auth_reset_password="1/min")
    )
    @patch("users.signals.EmailMultiAlternatives")
    def test_password_reset_request_post_is_scoped_throttled(self, _email_message):
        user = build_user(email="reset-throttle@example.com")

        first_response = self.client.post(
            "/auth/reset_password/",
            {"email": user.email},
            format="json",
            REMOTE_ADDR="203.0.113.13",
        )
        second_response = self.client.post(
            "/auth/reset_password/",
            {"email": user.email},
            format="json",
            REMOTE_ADDR="203.0.113.13",
        )

        self.assertNotEqual(first_response.status_code, 429)
        self.assertEqual(second_response.status_code, 429)
