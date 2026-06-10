from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject
from projects.models import Collaborator, Project

from .helpers import (
    add_program_member,
    create_collaborator,
    create_partner_program,
    create_project,
    create_user,
)


class ProjectDuplicateToProgramRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="project-duplicate-user")
        self.program = create_partner_program(name="Duplicate target program")
        add_program_member(self.program, self.user)
        self.client.force_authenticate(self.user)

    def test_duplicate_project_copies_data_collaborators_and_binds_to_program(self):
        original_project = create_project(
            leader=self.user,
            name="Original project",
            description="Original project description",
            draft=False,
            is_public=True,
        )
        original_project.region = "Moscow"
        original_project.actuality = "Important problem"
        original_project.problem = "Known bottleneck"
        original_project.target_audience = "Researchers"
        original_project.trl = 5
        original_project.save()

        teammate = create_user(prefix="project-duplicate-teammate")
        create_collaborator(
            original_project,
            user=teammate,
            role="Engineer",
            specialization="Backend",
        )

        response = self.client.post(
            "/projects/assign-to-program/",
            {
                "project_id": original_project.id,
                "partner_program_id": self.program.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        new_project = Project.objects.get(pk=response.data["new_project_id"])
        self.assertNotEqual(new_project.id, original_project.id)
        self.assertEqual(new_project.name, original_project.name)
        self.assertEqual(new_project.description, original_project.description)
        self.assertEqual(new_project.region, original_project.region)
        self.assertEqual(new_project.actuality, original_project.actuality)
        self.assertEqual(new_project.problem, original_project.problem)
        self.assertEqual(new_project.target_audience, original_project.target_audience)
        self.assertEqual(new_project.trl, original_project.trl)
        self.assertEqual(new_project.industry, original_project.industry)
        self.assertEqual(new_project.leader, self.user)
        self.assertTrue(new_project.draft)
        self.assertFalse(new_project.is_public)
        self.assertTrue(
            PartnerProgramProject.objects.filter(
                project=new_project,
                partner_program=self.program,
            ).exists()
        )
        self.assertTrue(
            Collaborator.objects.filter(
                project=new_project,
                user=teammate,
                role="Engineer",
                specialization="Backend",
            ).exists()
        )

    def test_non_leader_cannot_duplicate_project_to_program(self):
        other_leader = create_user(prefix="project-duplicate-other-leader")
        original_project = create_project(leader=other_leader)

        response = self.client.post(
            "/projects/assign-to-program/",
            {
                "project_id": original_project.id,
                "partner_program_id": self.program.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            PartnerProgramProject.objects.filter(
                project__name=original_project.name,
                partner_program=self.program,
            ).exists()
        )
