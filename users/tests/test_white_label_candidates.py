"""Email-only participants are discoverable only by an authorized program peer."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.tests.helpers import add_user_to_program, build_partner_program, build_user


class WhiteLabelCandidateSearchTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.program = build_partner_program()
        self.other = build_partner_program(name="Другая программа")
        self.leader = build_user(email="leader@example.test")
        self.member = build_user(
            email="member@example.test",
            first_name="",
            last_name="",
            birthday=None,
            onboarding_stage=None,
        )
        self.outsider = build_user(email="outsider@example.test")
        add_user_to_program(self.leader, self.program)
        add_user_to_program(self.member, self.program)
        add_user_to_program(self.outsider, self.other)
        self.mode = override_settings(
            WHITE_LABEL_ENABLED=True,
            WHITE_LABEL_PROGRAM_ID=self.program.pk,
            WHITE_LABEL_BRAND_NAME="Чемпионат",
            WHITE_LABEL_FRONTEND_URL="https://championship.example.test",
            WHITE_LABEL_LOGO_URL="",
            WHITE_LABEL_FAVICON_URL="",
            WHITE_LABEL_LOGO_BACKGROUND="transparent",
        )
        self.mode.enable()
        self.addCleanup(self.mode.disable)
        self.client.force_authenticate(self.leader)

    def search(self, **overrides):
        query = {
            "fullname": self.member.email,
            "partner_program": self.program.pk,
            "user_type": 1,
            **overrides,
        }
        return self.client.get("/auth/public-users/", query)

    def test_exact_email_finds_peer_without_inventing_profile_fields(self):
        response = self.search(fullname="  MEMBER@EXAMPLE.TEST  ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], self.member.pk)
        self.assertEqual(row["email"], self.member.email)
        self.assertEqual(row["firstName"], "")
        self.assertEqual(row["lastName"], "")
        self.assertIsNone(row["birthday"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("Authorization", response["Vary"])

    def test_anonymous_and_foreign_actor_cannot_search_email(self):
        for actor in (None, self.outsider):
            with self.subTest(actor=getattr(actor, "pk", None)):
                self.client.force_authenticate(actor)
                response = self.search()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 0)

    def test_foreign_candidate_and_program_are_not_disclosed(self):
        self.assertEqual(self.search(fullname=self.outsider.email).data["count"], 0)
        self.assertEqual(
            self.search(partner_program=self.other.pk, fullname=self.outsider.email).data[
                "count"
            ],
            0,
        )

    def test_missing_program_and_partial_email_do_not_enable_lookup(self):
        for query in (
            {"fullname": self.member.email},
            {"fullname": "member@", "partner_program": self.program.pk},
        ):
            response = self.client.get("/auth/public-users/", query)
            self.assertEqual(response.data["count"], 0)

    def test_named_search_and_public_list_do_not_expose_email(self):
        for actor in (None, self.leader):
            self.client.force_authenticate(actor)
            for query in (
                {},
                {"fullname": self.leader.first_name, "partner_program": self.program.pk},
            ):
                response = self.client.get("/auth/public-users/", query)
                self.assertTrue(response.data["results"])
                for row in response.data["results"]:
                    self.assertNotIn("email", row)

    def test_disabled_white_label_preserves_original_contract(self):
        with override_settings(WHITE_LABEL_ENABLED=False):
            self.assertEqual(self.search().data["count"], 0)
            response = self.search(fullname=self.leader.first_name)
            self.assertTrue(response.data["results"])
            self.assertNotIn("email", response.data["results"][0])

    def test_program_manager_can_find_own_participant(self):
        manager = build_user(email="manager@example.test")
        self.program.managers.add(manager)
        self.client.force_authenticate(manager)
        self.assertEqual(self.search().data["count"], 1)

    def test_other_filters_remain_effective(self):
        self.assertEqual(self.search(user_type=2).data["count"], 0)
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.assertEqual(self.search().data["count"], 0)
