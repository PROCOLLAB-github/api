"""Case is optional on draft apply, mandatory on submit, and scoped to its link."""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramFieldValue, PartnerProgramProject
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
    project_apply_payload,
)
from partner_programs.tests.test_case_fields import create_case_field


class ProgramCaseLifecycleAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user()
        self.client.force_authenticate(self.user)
        self.program = create_partner_program(is_competitive=True)
        create_program_member(self.program, user=self.user)
        self.field = create_case_field(self.program)
        self.apply_url = f"/programs/{self.program.pk}/projects/apply/"

    def apply(self, values=None):
        return self.client.post(
            self.apply_url,
            project_apply_payload(program_field_values=values),
            format="json",
        )

    def link(self):
        return create_program_project(
            self.program, project=create_project(leader=self.user, draft=True)
        )

    def submit(self, link):
        return self.client.post(f"/programs/partner-program-projects/{link.pk}/submit/")

    def assert_not_submitted(self, link, expected_date=None):
        link.refresh_from_db()
        self.assertFalse(link.submitted)
        self.assertEqual(link.datetime_submitted, expected_date)

    def test_draft_apply_without_case_does_not_choose_first_option(self):
        response = self.apply()
        self.assertEqual(response.status_code, 201)
        link = PartnerProgramProject.objects.get(pk=response.data["program_link_id"])
        self.assertTrue(link.project.draft)
        self.assertFalse(link.submitted)
        self.assertFalse(link.field_values.exists())

    def test_apply_with_explicit_valid_case_preserves_choice(self):
        response = self.apply([{"field_id": self.field.pk, "value_text": "B"}])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(PartnerProgramFieldValue.objects.get().value_text, "B")

    def test_apply_explicit_invalid_case_does_not_create_project(self):
        for value in (None, "", "unknown"):
            self.assertEqual(
                self.apply(
                    [{"field_id": self.field.pk, "value_text": value}]
                ).status_code,
                400,
            )
        self.assertFalse(PartnerProgramProject.objects.exists())

    def test_other_required_fields_remain_required_on_apply(self):
        field = create_program_field(self.program, name="track", is_required=True)
        self.assertEqual(self.apply().status_code, 400)
        self.assertEqual(
            self.apply([{"field_id": field.pk, "value_text": "answer"}]).status_code, 201
        )

    def test_submit_missing_case_has_controlled_error_without_date_change(self):
        link = self.link()
        original = timezone.now() - timezone.timedelta(days=1)
        link.datetime_submitted = original
        link.save()
        response = self.submit(link)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Выберите кейс перед сдачей проекта.")
        self.assert_not_submitted(link, original)

    def test_submit_empty_legacy_value_is_rejected_atomically(self):
        link = self.link()
        value = PartnerProgramFieldValue.objects.create(
            program_project=link, field=self.field, value_text="A"
        )
        for text in ("", " "):
            PartnerProgramFieldValue.objects.filter(pk=value.pk).update(value_text=text)
            response = self.submit(link)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.data["detail"], "Выберите кейс перед сдачей проекта."
            )
            self.assert_not_submitted(link)

    def test_submit_stale_legacy_value_is_rejected_atomically(self):
        link = self.link()
        value = PartnerProgramFieldValue.objects.create(
            program_project=link, field=self.field, value_text="A"
        )
        PartnerProgramFieldValue.objects.filter(pk=value.pk).update(
            value_text="deleted old option"
        )
        response = self.submit(link)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["detail"],
            "Выбранный кейс больше недоступен. Выберите актуальный кейс.",
        )
        self.assert_not_submitted(link)

    def test_submit_valid_case_freezes_fields(self):
        link = self.link()
        PartnerProgramFieldValue.objects.create(
            program_project=link, field=self.field, value_text="B"
        )
        self.assertEqual(self.submit(link).status_code, 200)
        link.refresh_from_db()
        self.assertTrue(link.submitted)
        self.assertIsNotNone(link.datetime_submitted)
        response = self.client.put(
            f"/programs/partner-program-projects/{link.pk}/fields/",
            [{"field_id": self.field.pk, "value_text": "C"}],
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(link.field_values.get().value_text, "B")

    def test_other_program_case_does_not_satisfy_current_link_submission(self):
        link = self.link()
        program_b = create_partner_program(is_competitive=True)
        field_b = create_case_field(program_b, options=["Other"])
        link_b = create_program_project(program_b, project=link.project)
        PartnerProgramFieldValue.objects.create(
            program_project=link_b, field=field_b, value_text="Other"
        )
        self.assertEqual(self.submit(link).status_code, 400)
        self.assert_not_submitted(link)
        self.assertEqual(self.submit(link_b).status_code, 200)

    def test_no_case_preserves_previous_submission_behavior(self):
        self.field.delete()
        link = self.link()
        self.assertEqual(self.submit(link).status_code, 200)
