from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
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

    @override_settings(PROGRAM_SOLUTIONS_ENABLED=False)
    def test_search_filters_published_catalog_by_name_before_pagination(self):
        match = create_partner_program(name="Первая смена названия")
        recent = create_partner_program(name="Другая программа", tag="первая смена")
        create_partner_program(name="Первая смена, черновик", draft=True)
        create_partner_program(
            name="Первая смена, решения", solution_storage_mode="solution"
        )

        first_page = self.client.get("/programs/", {"limit": 1})
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual([row["id"] for row in first_page.data["results"]], [recent.id])

        for query in ("Первая смена", "  Первая смена  "):
            with self.subTest(query=query):
                result = self.client.get("/programs/", {"search": query, "limit": 1})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.data["count"], 1)
                self.assertIsNone(result.data["next"])
                self.assertEqual(
                    [row["id"] for row in result.data["results"]], [match.id]
                )

        for query in ("", "   "):
            with self.subTest(query=query):
                result = self.client.get("/programs/", {"search": query, "limit": 1})
                self.assertEqual(result.data["results"], first_page.data["results"])
                self.assertEqual(result.data["count"], first_page.data["count"])

    def test_search_ignores_ascii_case(self):
        match = create_partner_program(name="First Shift")

        result = self.client.get("/programs/", {"search": "FIRST shift"})

        self.assertEqual(result.status_code, 200)
        self.assertEqual([row["id"] for row in result.data["results"]], [match.id])

    def test_postgresql_search_ignores_cyrillic_case(self):
        if connection.vendor != "postgresql":
            self.skipTest("SQLite LIKE ignores case only for ASCII")
        match = create_partner_program(name="Первая смена названия")

        result = self.client.get("/programs/", {"search": "  пЕРВАЯ СМЕНА  "})

        self.assertEqual(result.status_code, 200)
        self.assertEqual([row["id"] for row in result.data["results"]], [match.id])

    def test_catalog_paginates_by_creation_date_then_id(self):
        first_tie = create_partner_program()
        second_tie = create_partner_program()
        older = create_partner_program()
        now = timezone.now()
        PartnerProgram.objects.filter(pk__in=[first_tie.pk, second_tie.pk]).update(
            datetime_created=now
        )
        PartnerProgram.objects.filter(pk=older.pk).update(
            datetime_created=now - timezone.timedelta(days=1)
        )

        first = self.client.get("/programs/", {"limit": 1})
        second = self.client.get("/programs/", {"limit": 1, "offset": 1})
        third = self.client.get("/programs/", {"limit": 1, "offset": 2})

        self.assertEqual(
            [response.status_code for response in (first, second, third)], [200, 200, 200]
        )
        self.assertEqual(
            [response.data["results"][0]["id"] for response in (first, second, third)],
            [second_tie.id, first_tie.id, older.id],
        )

    def test_search_combines_with_participation_and_submission_filters(self):
        user = create_user()
        match = create_partner_program(name="Открытая программа", is_competitive=True)
        closed = create_partner_program(
            name="Открытая для просмотра",
            is_competitive=True,
            datetime_project_submission_ends=timezone.now() - timezone.timedelta(days=1),
        )
        create_partner_program(name="Открытая для других", is_competitive=True)
        different_name = create_partner_program(
            name="Другая программа", is_competitive=True
        )
        for program in (match, closed, different_name):
            create_program_member(program, user=user)
        query = {
            "search": "Открытая",
            "participating": "true",
            "project_submission": "true",
        }

        anonymous = self.client.get("/programs/", query)
        self.assertEqual(anonymous.status_code, 200)
        self.assertEqual(anonymous.data["count"], 0)

        self.client.force_authenticate(user)
        result = self.client.get("/programs/", query)
        self.assertEqual(result.status_code, 200)
        self.assertEqual([row["id"] for row in result.data["results"]], [match.id])
        self.assertTrue(result.data["results"][0]["is_user_member"])

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

    @patch("partner_programs.services.registration.send_email.delay")
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

    @patch("partner_programs.services.registration.send_email.delay")
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

    @patch("partner_programs.services.registration.send_email.delay")
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

    @patch("partner_programs.services.registration.send_email.delay")
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

    @patch("partner_programs.services.registration.send_email.delay")
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

    @patch("partner_programs.services.registration.send_email.delay")
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

    @patch("partner_programs.services.registration.send_email.delay")
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

    @patch("partner_programs.services.registration.send_email.delay")
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

    @patch("partner_programs.services.registration.send_email.delay")
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
