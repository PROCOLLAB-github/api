"""Real parent change POST + inline formset, for generic and reserved case values."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from partner_programs.models import PartnerProgramFieldValue
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_project,
    create_user,
)
from partner_programs.tests.test_case_fields import create_case_field


FREEZE_MESSAGE = (
    "Нельзя изменять значения полей программы после сдачи проекта на проверку."
)


class FieldValueAdminFlow:
    """The same admin freeze rules must apply to generic and case presentations."""

    is_case = False

    def setUp(self):
        self.user = create_user(is_staff=True, is_superuser=True, is_active=True)
        self.client.force_login(self.user)
        self.program = create_partner_program(is_competitive=True)
        self.link = create_program_project(self.program)
        self.field = (
            create_case_field(self.program, options=["rgdftb", "A", "B"])
            if self.is_case
            else create_program_field(self.program)
        )
        self.value = PartnerProgramFieldValue.objects.create(
            program_project=self.link, field=self.field, value_text="rgdftb"
        )
        self.url = reverse(
            "admin:partner_programs_partnerprogramproject_change", args=[self.link.pk]
        )
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200, page.get("Location"))
        self.prefix = page.context["inline_admin_formsets"][0].formset.prefix

    def payload(self, *, submitted=True, value="rgdftb"):
        data = {
            "partner_program": self.program.pk,
            "project": self.link.project_id,
            "datetime_submitted_0": "",
            "datetime_submitted_1": "",
            f"{self.prefix}-TOTAL_FORMS": "1",
            f"{self.prefix}-INITIAL_FORMS": "1",
            f"{self.prefix}-0-id": self.value.pk,
            f"{self.prefix}-0-program_project": self.link.pk,
            f"{self.prefix}-0-field": self.field.pk,
            f"{self.prefix}-0-value_text": value,
            "_save": "Сохранить",
        }
        if submitted:
            data["submitted"] = "on"
        return data

    def freeze(self):
        self.link.submitted = True
        self.link.save(update_fields=["submitted"])

    def assert_rejected(self, data, *, submitted):
        expected_value = self.value.value_text
        response = self.client.post(self.url, data)
        self.assertContains(response, FREEZE_MESSAGE, status_code=200)
        self.link.refresh_from_db()
        self.value.refresh_from_db()
        self.assertEqual(self.link.submitted, submitted)
        self.assertIsNone(self.link.datetime_submitted)
        self.assertEqual(self.value.value_text, expected_value)
        self.assertEqual(self.value.field_id, self.field.pk)
        self.assertEqual(self.link.field_values.count(), 1)

    def test_submit_with_unchanged_inline_redirects_and_preserves_row(self):
        response = self.client.post(self.url, self.payload())
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.value.refresh_from_db()
        self.assertTrue(self.link.submitted)
        self.assertEqual(self.value.value_text, "rgdftb")
        self.assertEqual(self.value.field_id, self.field.pk)
        self.assertEqual(self.link.field_values.count(), 1)

    def test_submit_and_edit_in_one_post_is_rejected_atomically(self):
        self.value.value_text = "A"
        self.value.save()
        self.assert_rejected(self.payload(value="B"), submitted=False)

    def test_edit_after_submission_is_rejected(self):
        self.freeze()
        self.assert_rejected(self.payload(value="B"), submitted=True)

    def test_changing_field_after_submission_is_rejected(self):
        other_field = create_program_field(self.program)
        self.freeze()
        data = self.payload()
        data[f"{self.prefix}-0-field"] = other_field.pk
        self.assert_rejected(data, submitted=True)

    def test_add_after_submission_is_rejected(self):
        other_field = create_program_field(self.program)
        self.freeze()
        data = self.payload()
        data.update(
            {
                f"{self.prefix}-TOTAL_FORMS": "2",
                f"{self.prefix}-1-id": "",
                f"{self.prefix}-1-program_project": self.link.pk,
                f"{self.prefix}-1-field": other_field.pk,
                f"{self.prefix}-1-value_text": "new",
            }
        )
        self.assert_rejected(data, submitted=True)

    def test_delete_after_submission_is_rejected(self):
        self.freeze()
        data = self.payload()
        data[f"{self.prefix}-0-DELETE"] = "on"
        self.assert_rejected(data, submitted=True)

    def test_submit_and_delete_in_one_post_is_rejected_atomically(self):
        data = self.payload()
        data[f"{self.prefix}-0-DELETE"] = "on"
        self.assert_rejected(data, submitted=False)

    def test_submit_and_add_in_one_post_is_rejected_atomically(self):
        other_field = create_program_field(self.program)
        data = self.payload()
        data.update(
            {
                f"{self.prefix}-TOTAL_FORMS": "2",
                f"{self.prefix}-1-id": "",
                f"{self.prefix}-1-program_project": self.link.pk,
                f"{self.prefix}-1-field": other_field.pk,
                f"{self.prefix}-1-value_text": "new",
            }
        )
        self.assert_rejected(data, submitted=False)

    def test_unsubmit_and_edit_cannot_bypass_persisted_freeze(self):
        self.freeze()
        self.assert_rejected(self.payload(submitted=False, value="B"), submitted=True)

    def test_unsubmit_and_delete_cannot_bypass_persisted_freeze(self):
        self.freeze()
        data = self.payload(submitted=False)
        data[f"{self.prefix}-0-DELETE"] = "on"
        self.assert_rejected(data, submitted=True)

    def test_unchanged_submitted_inline_allows_unrelated_parent_metadata_edit(self):
        self.freeze()
        data = self.payload()
        date = timezone.localtime(timezone.now()).replace(microsecond=0)
        data["datetime_submitted_0"] = date.strftime("%Y-%m-%d")
        data["datetime_submitted_1"] = date.strftime("%H:%M:%S")
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.value.refresh_from_db()
        self.assertTrue(self.link.submitted)
        self.assertEqual(self.link.datetime_submitted, date)
        self.assertEqual(self.value.value_text, "rgdftb")

    def test_edit_before_submission_still_saves(self):
        response = self.client.post(self.url, self.payload(submitted=False, value="B"))
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.value.refresh_from_db()
        self.assertFalse(self.link.submitted)
        self.assertEqual(self.value.value_text, "B")

    def test_delete_before_submission_still_saves(self):
        data = self.payload(submitted=False)
        data[f"{self.prefix}-0-DELETE"] = "on"
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.link.refresh_from_db()
        self.assertFalse(self.link.submitted)
        self.assertFalse(self.link.field_values.exists())


class GenericFieldValueAdminTests(FieldValueAdminFlow, TestCase):
    pass


class CaseFieldValueAdminTests(FieldValueAdminFlow, TestCase):
    is_case = True
