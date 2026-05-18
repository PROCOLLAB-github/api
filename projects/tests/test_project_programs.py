from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile

from .helpers import (
    add_program_member,
    create_industry,
    create_partner_program,
    create_user,
)


class ProjectProgramBindingRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="project-program-user")
        self.industry = create_industry()
        self.client.force_authenticate(self.user)

    def test_program_member_can_create_project_bound_to_program(self):
        program = create_partner_program()
        member_profile = add_program_member(program, self.user)

        response = self.client.post(
            "/projects/",
            {
                "name": "Program project",
                "description": "Project for partner program",
                "industry": self.industry.id,
                "partner_program_id": program.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        project_id = response.data["id"]
        self.assertTrue(
            PartnerProgramProject.objects.filter(
                project_id=project_id,
                partner_program=program,
            ).exists()
        )
        member_profile.refresh_from_db()
        self.assertEqual(member_profile.project_id, project_id)
        self.assertFalse(member_profile.project.is_public)

    def test_user_cannot_create_project_for_program_without_membership(self):
        program = create_partner_program()

        response = self.client.post(
            "/projects/",
            {
                "name": "Foreign program project",
                "description": "Project for unavailable partner program",
                "industry": self.industry.id,
                "partner_program_id": program.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            PartnerProgramUserProfile.objects.filter(
                user=self.user,
                partner_program=program,
            ).exists()
        )
        self.assertFalse(
            PartnerProgramProject.objects.filter(partner_program=program).exists()
        )
