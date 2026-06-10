from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramFieldValue
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_project,
    create_project,
    create_user,
)


class PartnerProgramFieldValueBulkUpdateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="program-fields-leader")
        self.program = create_partner_program()
        self.project = create_project(leader=self.leader)
        self.program_link = create_program_project(self.program, project=self.project)
        self.field = create_program_field(self.program, name="track")

    def test_project_leader_can_update_program_field_values(self):
        self.client.force_authenticate(self.leader)

        response = self.client.put(
            f"/projects/{self.project.id}/program-fields/",
            [{"field_id": self.field.id, "value_text": "ai"}],
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        value = PartnerProgramFieldValue.objects.get(
            program_project=self.program_link,
            field=self.field,
        )
        self.assertEqual(value.value_text, "ai")

    def test_non_leader_cannot_update_program_field_values(self):
        outsider = create_user(prefix="program-fields-outsider")
        self.client.force_authenticate(outsider)

        response = self.client.put(
            f"/projects/{self.project.id}/program-fields/",
            [{"field_id": self.field.id, "value_text": "ai"}],
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(PartnerProgramFieldValue.objects.exists())

    def test_submitted_competitive_project_fields_cannot_be_changed(self):
        self.program.is_competitive = True
        self.program.save(update_fields=["is_competitive"])
        self.program_link.submitted = True
        self.program_link.save(update_fields=["submitted"])
        self.client.force_authenticate(self.leader)

        response = self.client.put(
            f"/projects/{self.project.id}/program-fields/",
            [{"field_id": self.field.id, "value_text": "ai"}],
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PartnerProgramFieldValue.objects.exists())

    def test_field_from_another_program_is_rejected(self):
        other_program = create_partner_program(name="Other field program")
        other_field = create_program_field(other_program, name="foreign")
        self.client.force_authenticate(self.leader)

        response = self.client.put(
            f"/projects/{self.project.id}/program-fields/",
            [{"field_id": other_field.id, "value_text": "foreign"}],
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PartnerProgramFieldValue.objects.exists())
