from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

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
