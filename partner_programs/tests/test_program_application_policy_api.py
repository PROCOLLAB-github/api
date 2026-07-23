from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from partner_programs.models import Application, PartnerProgram
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)


class PartnerProgramApplicationPolicyAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def get_policy(self, program: PartnerProgram) -> dict:
        response = self.client.get(f"/programs/{program.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("application_policy", response.data)
        return response.data["application_policy"]

    def test_individual_only_detail_exposes_individual_policy(self):
        program = create_partner_program(
            participation_format=(PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_ONLY),
            team_min_size=None,
            team_max_size=None,
            datetime_application_ends=None,
        )

        policy = self.get_policy(program)

        self.assertEqual(
            policy,
            {
                "participation_format": "individual_only",
                "allowed_participation_modes": [
                    Application.PARTICIPATION_MODE_INDIVIDUAL
                ],
                "team_min_size": None,
                "team_max_size": None,
                "datetime_application_ends": None,
                "is_application_deadline_passed": False,
            },
        )
        self.assertNotIn(
            Application.PARTICIPATION_MODE_UNDECIDED,
            policy["allowed_participation_modes"],
        )

    def test_team_only_detail_exposes_sizes_and_future_deadline(self):
        deadline = timezone.now() + timezone.timedelta(days=10)
        program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=5,
            datetime_application_ends=deadline,
        )

        policy = self.get_policy(program)

        self.assertEqual(policy["participation_format"], "team_only")
        self.assertEqual(
            policy["allowed_participation_modes"],
            [Application.PARTICIPATION_MODE_TEAM],
        )
        self.assertEqual(policy["team_min_size"], 2)
        self.assertEqual(policy["team_max_size"], 5)
        self.assertEqual(parse_datetime(policy["datetime_application_ends"]), deadline)
        self.assertFalse(policy["is_application_deadline_passed"])
        self.assertNotIn(
            Application.PARTICIPATION_MODE_UNDECIDED,
            policy["allowed_participation_modes"],
        )

    def test_individual_or_team_detail_marks_passed_deadline(self):
        deadline = timezone.now() - timezone.timedelta(seconds=1)
        program = create_partner_program(
            participation_format=(PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM),
            team_min_size=2,
            team_max_size=4,
            datetime_application_ends=deadline,
        )

        policy = self.get_policy(program)

        self.assertEqual(policy["participation_format"], "individual_or_team")
        self.assertEqual(
            policy["allowed_participation_modes"],
            [
                Application.PARTICIPATION_MODE_INDIVIDUAL,
                Application.PARTICIPATION_MODE_TEAM,
            ],
        )
        self.assertEqual(policy["team_min_size"], 2)
        self.assertEqual(policy["team_max_size"], 4)
        self.assertEqual(parse_datetime(policy["datetime_application_ends"]), deadline)
        self.assertTrue(policy["is_application_deadline_passed"])
        self.assertNotIn(
            Application.PARTICIPATION_MODE_UNDECIDED,
            policy["allowed_participation_modes"],
        )

    def test_member_detail_uses_the_same_public_policy_contract(self):
        program = create_partner_program()
        member = create_user(prefix="policy-program-member")
        create_program_member(program, user=member)
        self.client.force_authenticate(member)

        policy = self.get_policy(program)

        self.assertEqual(policy["participation_format"], "individual_only")
        self.assertEqual(policy["allowed_participation_modes"], ["individual"])

    def test_program_list_contract_does_not_include_application_policy(self):
        create_partner_program()

        response = self.client.get("/programs/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("application_policy", response.data["results"][0])
