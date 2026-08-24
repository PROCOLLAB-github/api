from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)


class PartnerProgramWelcomeAcknowledgementTests(TestCase):
    """Проверяет одно приветствие для каждой пары пользователь–программа."""

    def setUp(self):
        self.client = APIClient()
        self.user_a = create_user(prefix="welcome-user-a")
        self.user_b = create_user(prefix="welcome-user-b")
        self.program_1 = create_partner_program(name="Welcome program 1")
        self.program_2 = create_partner_program(name="Welcome program 2")
        self.profile_a_1 = create_program_member(self.program_1, user=self.user_a)
        self.profile_a_2 = create_program_member(self.program_2, user=self.user_a)
        self.profile_b_1 = create_program_member(self.program_1, user=self.user_b)

    def test_detail_does_not_acknowledge_welcome_on_load(self):
        self.client.force_authenticate(self.user_a)

        response = self.client.get(f"/programs/{self.program_1.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_user_member"])
        self.assertIsNone(response.data["welcome_acknowledged_at"])
        self.profile_a_1.refresh_from_db()
        self.assertIsNone(self.profile_a_1.welcome_acknowledged_at)

    def test_welcome_acknowledgement_is_idempotent(self):
        self.client.force_authenticate(self.user_a)
        url = f"/programs/{self.program_1.id}/acknowledge-welcome/"

        first_response = self.client.post(url, format="json")
        second_response = self.client.post(url, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertIsNotNone(first_response.data["welcome_acknowledged_at"])
        self.assertEqual(
            second_response.data["welcome_acknowledged_at"],
            first_response.data["welcome_acknowledged_at"],
        )

    def test_acknowledgement_is_independent_for_another_program(self):
        self.client.force_authenticate(self.user_a)
        self.client.post(
            f"/programs/{self.program_1.id}/acknowledge-welcome/",
            format="json",
        )

        response = self.client.get(f"/programs/{self.program_2.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["welcome_acknowledged_at"])
        self.profile_a_2.refresh_from_db()
        self.assertIsNone(self.profile_a_2.welcome_acknowledged_at)

    def test_acknowledgement_is_independent_for_another_user(self):
        self.client.force_authenticate(self.user_a)
        self.client.post(
            f"/programs/{self.program_1.id}/acknowledge-welcome/",
            format="json",
        )

        self.client.force_authenticate(self.user_b)
        response = self.client.get(f"/programs/{self.program_1.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["welcome_acknowledged_at"])
        self.profile_b_1.refresh_from_db()
        self.assertIsNone(self.profile_b_1.welcome_acknowledged_at)

    def test_non_member_cannot_acknowledge_program_welcome(self):
        outsider = create_user(prefix="welcome-outsider")
        self.client.force_authenticate(outsider)

        response = self.client.post(
            f"/programs/{self.program_1.id}/acknowledge-welcome/",
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_cannot_acknowledge_program_welcome(self):
        response = self.client.post(
            f"/programs/{self.program_1.id}/acknowledge-welcome/",
            format="json",
        )

        self.assertEqual(response.status_code, 401)
