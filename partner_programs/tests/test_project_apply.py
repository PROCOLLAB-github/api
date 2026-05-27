from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramFieldValue, PartnerProgramProject
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_member,
    create_user,
    project_apply_payload,
)


class PartnerProgramProjectApplyAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="program-apply-user")
        self.program = create_partner_program()

    def test_member_can_get_project_apply_schema(self):
        create_program_member(self.program, user=self.user)
        field = create_program_field(
            self.program,
            name="track",
            label="Track",
            field_type="select",
            options=["ai", "edu"],
            is_required=True,
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/programs/{self.program.id}/projects/apply/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["program_id"], self.program.id)
        self.assertTrue(response.data["can_submit"])
        self.assertEqual(response.data["program_fields"][0]["id"], field.id)

    def test_non_member_cannot_apply_project(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/projects/apply/",
            project_apply_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_member_can_apply_project_with_program_field_values(self):
        profile = create_program_member(self.program, user=self.user)
        field = create_program_field(
            self.program,
            name="track",
            label="Track",
            field_type="select",
            options=["ai", "edu"],
            is_required=True,
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/projects/apply/",
            project_apply_payload(
                project={"name": "Program project"},
                program_field_values=[
                    {"field_id": field.id, "value_text": "ai"},
                ],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        program_link = PartnerProgramProject.objects.select_related("project").get(
            id=response.data["program_link_id"]
        )
        self.assertEqual(program_link.partner_program, self.program)
        self.assertEqual(program_link.project.leader, self.user)
        self.assertTrue(program_link.project.draft)
        self.assertFalse(program_link.project.is_public)
        self.assertEqual(program_link.project.name, "Program project")
        self.assertTrue(
            PartnerProgramFieldValue.objects.filter(
                program_project=program_link,
                field=field,
                value_text="ai",
            ).exists()
        )
        profile.refresh_from_db()
        self.assertEqual(profile.project, program_link.project)

    def test_apply_project_rejects_duplicate_field_values(self):
        create_program_member(self.program, user=self.user)
        field = create_program_field(self.program, name="track")
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/projects/apply/",
            project_apply_payload(
                program_field_values=[
                    {"field_id": field.id, "value_text": "first"},
                    {"field_id": field.id, "value_text": "second"},
                ],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PartnerProgramProject.objects.exists())

    def test_apply_project_rejects_missing_required_program_fields(self):
        create_program_member(self.program, user=self.user)
        create_program_field(
            self.program,
            name="track",
            label="Track",
            is_required=True,
        )
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/projects/apply/",
            project_apply_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PartnerProgramProject.objects.exists())

    def test_apply_project_rejects_field_from_another_program(self):
        create_program_member(self.program, user=self.user)
        other_program = create_partner_program(name="Other program")
        other_field = create_program_field(other_program, name="foreign_field")
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/projects/apply/",
            project_apply_payload(
                program_field_values=[
                    {"field_id": other_field.id, "value_text": "foreign"},
                ],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PartnerProgramProject.objects.exists())

    def test_apply_project_is_blocked_after_submission_deadline(self):
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(days=1)
        )
        self.program.save(update_fields=["datetime_project_submission_ends"])
        create_program_member(self.program, user=self.user)
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/programs/{self.program.id}/projects/apply/",
            project_apply_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data[0],
            "Срок подачи проектов в программу завершён.",
        )
