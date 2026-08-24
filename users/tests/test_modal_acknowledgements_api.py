from django.test import TestCase
from rest_framework.test import APIClient

from .helpers import build_user


class UserModalAcknowledgementAPITests(TestCase):
    """Проверяет account-level подтверждения пользовательских системных окон."""

    def setUp(self):
        self.client = APIClient()
        self.user = build_user(email="modal-acknowledgements@example.com")
        self.client.force_authenticate(self.user)

    def test_current_user_exposes_unacknowledged_notice_state(self):
        response = self.client.get("/auth/users/current/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["verification_notice_acknowledged_at"])
        self.assertIsNone(response.data["profile_fill_prompt_acknowledged_at"])

    def test_verification_notice_acknowledgement_is_idempotent(self):
        url = "/auth/users/current/acknowledge-verification-notice/"

        first_response = self.client.post(url, format="json")
        second_response = self.client.post(url, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertIsNotNone(first_response.data["verification_notice_acknowledged_at"])
        self.assertEqual(
            second_response.data["verification_notice_acknowledged_at"],
            first_response.data["verification_notice_acknowledged_at"],
        )

    def test_profile_fill_prompt_acknowledgement_is_idempotent(self):
        url = "/auth/users/current/acknowledge-profile-fill-prompt/"

        first_response = self.client.post(url, format="json")
        second_response = self.client.post(url, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertIsNotNone(first_response.data["profile_fill_prompt_acknowledged_at"])
        self.assertEqual(
            second_response.data["profile_fill_prompt_acknowledged_at"],
            first_response.data["profile_fill_prompt_acknowledged_at"],
        )

    def test_profile_update_cannot_reset_system_acknowledgements(self):
        self.client.post(
            "/auth/users/current/acknowledge-verification-notice/",
            format="json",
        )
        self.client.post(
            "/auth/users/current/acknowledge-profile-fill-prompt/",
            format="json",
        )
        self.user.refresh_from_db()
        verification_acknowledged_at = self.user.verification_notice_acknowledged_at
        profile_fill_acknowledged_at = self.user.profile_fill_prompt_acknowledged_at

        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {
                "verification_notice_acknowledged_at": None,
                "profile_fill_prompt_acknowledged_at": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.verification_notice_acknowledged_at,
            verification_acknowledged_at,
        )
        self.assertEqual(
            self.user.profile_fill_prompt_acknowledged_at,
            profile_fill_acknowledged_at,
        )

    def test_other_user_does_not_receive_private_acknowledgement_fields(self):
        other_user = build_user(email="other-modal-user@example.com")

        response = self.client.get(f"/auth/users/{other_user.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("verification_notice_acknowledged_at", response.data)
        self.assertNotIn("profile_fill_prompt_acknowledged_at", response.data)

    def test_acknowledgements_are_independent_for_another_account(self):
        self.client.post(
            "/auth/users/current/acknowledge-verification-notice/",
            format="json",
        )
        self.client.post(
            "/auth/users/current/acknowledge-profile-fill-prompt/",
            format="json",
        )
        other_user = build_user(email="independent-modal-user@example.com")
        self.client.force_authenticate(other_user)

        response = self.client.get("/auth/users/current/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["verification_notice_acknowledged_at"])
        self.assertIsNone(response.data["profile_fill_prompt_acknowledged_at"])

    def test_anonymous_user_cannot_acknowledge_notices(self):
        self.client.force_authenticate(user=None)

        verification_response = self.client.post(
            "/auth/users/current/acknowledge-verification-notice/",
            format="json",
        )
        profile_fill_response = self.client.post(
            "/auth/users/current/acknowledge-profile-fill-prompt/",
            format="json",
        )

        self.assertEqual(verification_response.status_code, 401)
        self.assertEqual(profile_fill_response.status_code, 401)
