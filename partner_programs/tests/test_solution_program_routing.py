"""Public routing metadata does not grant access to the program's private content."""

from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)
from project_rates.tests.helpers import create_rate_expert


class SolutionProgramRoutingTests(TestCase):
    def test_mode_is_explicit_for_member_expert_and_outsider_without_private_fields(self):
        client = APIClient()
        for mode in ("legacy_project", "solution"):
            program = create_partner_program(
                solution_storage_mode=mode, description="Закрытое описание"
            )
            member = create_user()
            create_program_member(program, user=member)
            expert = create_rate_expert(program=program)
            outsider = create_user()
            for user in (member, expert, outsider):
                with self.subTest(mode=mode, user=user.pk):
                    client.force_authenticate(user)
                    response = client.get(f"/programs/{program.pk}/")
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["solution_storage_mode"], mode)
                    self.assertNotIn("solutions", response.data)
                    self.assertNotIn("submission_snapshot", response.data)
                    if user != member:
                        self.assertNotIn("description", response.data)
                        self.assertNotIn("links", response.data)

    def test_routing_metadata_is_read_only_on_both_serializer_variants(self):
        from partner_programs.serializers.programs import (
            PartnerProgramForMemberSerializer,
            PartnerProgramForUnregisteredUserSerializer,
        )

        for serializer in (
            PartnerProgramForMemberSerializer,
            PartnerProgramForUnregisteredUserSerializer,
        ):
            self.assertTrue(serializer().fields["solution_storage_mode"].read_only)
