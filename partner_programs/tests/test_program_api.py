from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramUserProfile
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)


class PartnerProgramListAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_list_returns_only_published_programs(self):
        published = create_partner_program(name="Published program", draft=False)
        draft = create_partner_program(name="Draft program", draft=True)

        response = self.client.get("/programs/")

        self.assertEqual(response.status_code, 200)
        program_ids = {item["id"] for item in response.data["results"]}
        self.assertIn(published.id, program_ids)
        self.assertNotIn(draft.id, program_ids)

    def test_participating_filter_returns_active_programs_for_current_user(self):
        user = create_user(prefix="program-list-member")
        active_program = create_partner_program(
            name="Active member program",
            datetime_finished=timezone.now() + timezone.timedelta(days=10),
        )
        finished_program = create_partner_program(
            name="Finished member program",
            datetime_finished=timezone.now() - timezone.timedelta(days=1),
        )
        other_program = create_partner_program(name="Other program")
        create_program_member(active_program, user=user)
        create_program_member(finished_program, user=user)
        self.client.force_authenticate(user)

        response = self.client.get("/programs/?participating=1")

        self.assertEqual(response.status_code, 200)
        program_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(program_ids, {active_program.id})
        self.assertNotIn(other_program.id, program_ids)
        self.assertTrue(response.data["results"][0]["is_user_member"])


class PartnerProgramRegisterAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="program-register-user")
        self.program = create_partner_program()

    @patch("partner_programs.services.send_email.delay")
    def test_authenticated_user_can_register_to_program(self, send_email_delay):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/register/",
            {"telegram": "@program_user"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        profile = PartnerProgramUserProfile.objects.get(
            user=self.user,
            partner_program=self.program,
        )
        self.assertEqual(profile.partner_program_data, {"telegram": "@program_user"})
        send_email_delay.assert_called_once()

    @patch("partner_programs.services.send_email.delay")
    def test_authenticated_user_cannot_register_twice(self, send_email_delay):
        create_program_member(self.program, user=self.user)
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/register/",
            {"telegram": "@program_user"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["detail"],
            "User already registered to this program.",
        )
        send_email_delay.assert_not_called()

    @patch("partner_programs.services.send_email.delay")
    def test_registration_is_blocked_after_deadline(self, send_email_delay):
        self.program.datetime_registration_ends = timezone.now() - timezone.timedelta(
            days=1
        )
        self.program.save(update_fields=["datetime_registration_ends"])
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/register/",
            {"telegram": "@program_user"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Registration period has ended.")
        send_email_delay.assert_not_called()

    @patch("partner_programs.services.send_email.delay")
    def test_external_registration_creates_user_and_program_profile(
        self,
        send_email_delay,
    ):
        response = self.client.post(
            f"/programs/{self.program.id}/register_new/",
            {
                "email": "external-program-user@example.com",
                "password": "pass",
                "first_name": "External",
                "last_name": "User",
                "birthday": "01-01-1990",
                "telegram": "@external",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        profile = PartnerProgramUserProfile.objects.select_related("user").get(
            partner_program=self.program,
            user__email="external-program-user@example.com",
        )
        self.assertTrue(profile.user.is_active)
        self.assertEqual(profile.partner_program_data["telegram"], "@external")
        send_email_delay.assert_called_once()

    @patch("partner_programs.services.send_email.delay")
    def test_external_registration_accepts_email_compatibility_field(
        self,
        send_email_delay,
    ):
        response = self.client.post(
            f"/programs/{self.program.id}/register_new/",
            {
                "email_": "external-email-field@example.com",
                "password": "pass",
                "first_name": "External",
                "last_name": "User",
                "birthday": "01-01-1990",
                "telegram": "@external_email_field",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        profile = PartnerProgramUserProfile.objects.select_related("user").get(
            partner_program=self.program,
            user__email="external-email-field@example.com",
        )
        self.assertEqual(profile.partner_program_data["email_"], profile.user.email)
        self.assertEqual(
            profile.partner_program_data["telegram"],
            "@external_email_field",
        )
        send_email_delay.assert_called_once()

    @patch("partner_programs.services.send_email.delay")
    def test_external_registration_test_ping_does_not_create_profile(
        self,
        send_email_delay,
    ):
        response = self.client.post(
            f"/programs/{self.program.id}/register_new/",
            {"test": "test"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PartnerProgramUserProfile.objects.exists())
        send_email_delay.assert_not_called()

    @patch("partner_programs.services.send_email.delay")
    def test_external_registration_requires_email(self, send_email_delay):
        response = self.client.post(
            f"/programs/{self.program.id}/register_new/",
            {
                "password": "pass",
                "first_name": "External",
                "last_name": "User",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "You need to pass an email address.")
        self.assertFalse(PartnerProgramUserProfile.objects.exists())
        send_email_delay.assert_not_called()

    @patch("partner_programs.services.send_email.delay")
    def test_external_registration_requires_password(self, send_email_delay):
        response = self.client.post(
            f"/programs/{self.program.id}/register_new/",
            {
                "email": "external-no-password@example.com",
                "first_name": "External",
                "last_name": "User",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "You need to pass a password.")
        self.assertFalse(PartnerProgramUserProfile.objects.exists())
        send_email_delay.assert_not_called()

    @patch("partner_programs.services.send_email.delay")
    def test_external_registration_rejects_duplicate_program_profile(
        self,
        send_email_delay,
    ):
        create_program_member(self.program, user=self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/register_new/",
            {
                "email": self.user.email,
                "password": "pass",
                "first_name": "External",
                "last_name": "User",
                "birthday": "01-01-1990",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["detail"],
            "User has already registered in this program.",
        )
        send_email_delay.assert_not_called()
