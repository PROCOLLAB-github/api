from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import CustomUser

from .helpers import build_superuser, build_user


class UserOnboardingAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = build_user(email="onboarding@example.com")
        self.client.force_authenticate(user=self.user)

    def test_user_can_update_own_onboarding_stage(self):
        response = self.client.put(
            f"/auth/users/{self.user.id}/set_onboarding_stage/",
            {"onboarding_stage": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_stage, 1)

    def test_user_cannot_update_another_user_onboarding_stage(self):
        other_user = build_user(email="other-onboarding@example.com")

        response = self.client.put(
            f"/auth/users/{other_user.id}/set_onboarding_stage/",
            {"onboarding_stage": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        other_user.refresh_from_db()
        self.assertNotEqual(other_user.onboarding_stage, 1)

    def test_user_cannot_set_invalid_onboarding_stage(self):
        response = self.client.put(
            f"/auth/users/{self.user.id}/set_onboarding_stage/",
            {"onboarding_stage": 4},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class UserVerificationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("users.views.verify_email")
    def test_resend_verify_email_for_inactive_user(self, verify_email_mock):
        user = build_user(email="inactive@example.com", is_active=False)

        response = self.client.post(
            "/auth/resend_email/",
            {"email": user.email},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        verify_email_mock.assert_called_once()

    @patch("users.views.verify_email")
    def test_resend_verify_email_does_not_send_for_active_user(self, verify_email_mock):
        user = build_user(email="active@example.com", is_active=True)

        response = self.client.post(
            "/auth/resend_email/",
            {"email": user.email},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        verify_email_mock.assert_not_called()

    def test_admin_can_force_verify_user(self):
        admin = build_superuser()
        user = build_user(email="force@example.com", is_active=False)
        self.client.force_authenticate(user=admin)

        response = self.client.post(f"/auth/users/{user.id}/force_verify/")

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.verification_date, timezone.now().date())

    def test_regular_user_cannot_force_verify_user(self):
        actor = build_user(email="regular@example.com")
        user = build_user(email="target@example.com", is_active=False)
        self.client.force_authenticate(user=actor)

        response = self.client.post(f"/auth/users/{user.id}/force_verify/")

        self.assertEqual(response.status_code, 403)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_user_type_signal_creates_role_profile(self):
        expert = build_user(
            email="expert-profile@example.com",
            user_type=CustomUser.EXPERT,
        )

        self.assertTrue(hasattr(expert, "expert"))
