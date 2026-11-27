from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject
from partner_programs.tests.helpers import create_program_field
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

    def assign(self, project):
        return self.client.post(
            "/projects/assign-to-program/",
            {"project_id": project.pk, "partner_program_id": self.program.pk},
            format="json",
        )

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

        response = self.assign(original_project)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["can_edit"])
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

        response = self.assign(original_project)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            PartnerProgramProject.objects.filter(
                project__name=original_project.name,
                partner_program=self.program,
            ).exists()
        )

    def test_retry_reuses_draft_then_submitted_copy_without_mutating_answers(self):
        self.program.is_competitive = True
        self.program.save(update_fields=["is_competitive"])
        source = create_project(leader=self.user)
        field = create_program_field(self.program, name="answer", is_required=True)
        initial = self.assign(source)
        self.assertEqual(initial.status_code, 201, initial.data)
        copy_id = initial.data["new_project_id"]
        link_id = initial.data["program_link_id"]
        project_count = Project.objects.count()

        draft_retry = self.assign(source)
        self.assertEqual(draft_retry.status_code, 200, draft_retry.data)
        self.assertEqual(draft_retry.data, initial.data)
        fields_url = f"/programs/partner-program-projects/{link_id}/fields/"
        self.assertEqual(
            self.client.put(
                fields_url,
                [{"field_id": field.pk, "value_text": "Saved answer"}],
                format="json",
            ).status_code,
            200,
        )
        submitted = self.client.post(f"/programs/partner-program-projects/{link_id}/submit/")
        self.assertEqual(submitted.status_code, 200, submitted.data)
        snapshot = PartnerProgramProject.objects.get(pk=link_id).submitted_form
        self.assertIsNotNone(snapshot)

        retry = self.assign(source)
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(retry.data["new_project_id"], copy_id)
        self.assertEqual(retry.data["program_link_id"], link_id)
        self.assertFalse(retry.data["can_edit"])
        self.assertEqual(Project.objects.count(), project_count)
        link = source.program_copies.get(partner_program=self.program)
        self.assertEqual(link.submitted_form, snapshot)
        self.assertEqual(link.field_values.get(field=field).value_text, "Saved answer")
        self.assertEqual(
            self.client.get(f"/projects/{source.pk}/").data["program_copies"],
            [
                {
                    "project_id": copy_id,
                    "program_id": self.program.pk,
                    "program_link_id": link_id,
                    "name": self.program.name,
                    "submitted": True,
                }
            ],
        )

    def test_same_name_without_source_relation_still_conflicts(self):
        source = create_project(leader=self.user)
        other = create_project(is_public=False)
        Project.objects.filter(pk=other.pk).update(name=source.name)
        PartnerProgramProject.objects.create(project=other, partner_program=self.program)
        project_count = Project.objects.count()

        retry = self.assign(source)

        self.assertEqual(retry.status_code, 400)
        self.assertNotIn("new_project_id", retry.data)
        self.assertNotIn("program_link_id", retry.data)
        self.assertEqual(Project.objects.count(), project_count)
        self.assertFalse(source.program_copies.exists())

    def test_private_copy_requires_independent_read_access(self):
        source = create_project(leader=self.user)
        copy = create_project(is_public=False)
        PartnerProgramProject.objects.create(
            project=copy, source_project=source, partner_program=self.program
        )

        self.assertEqual(
            self.client.get(f"/projects/{source.pk}/").data["program_copies"], []
        )
        denied = self.assign(source)
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assertNotIn("new_project_id", denied.data)
        self.assertNotIn("program_link_id", denied.data)

        create_collaborator(copy, user=self.user)
        retry = self.assign(source)
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(retry.data["new_project_id"], copy.pk)
        self.assertFalse(retry.data["can_edit"])
        self.assertEqual(self.client.get(f"/projects/{copy.pk}/").status_code, 200)
