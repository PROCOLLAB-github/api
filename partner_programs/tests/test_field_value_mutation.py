"""DB identity and parent state determine freeze; unchanged validation is safe."""

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramFieldValue, PartnerProgramProject
from partner_programs.services.field_values import FIELD_VALUES_FROZEN_MESSAGE
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_project,
)
from partner_programs.tests.test_case_fields import create_case_field


class ProgramFieldValueMutationTests(TestCase):
    def setUp(self):
        self.program = create_partner_program(is_competitive=True)
        self.link = create_program_project(self.program)
        self.generic = create_program_field(self.program)
        self.case = create_case_field(self.program)
        self.values = [
            PartnerProgramFieldValue.objects.create(
                program_project=self.link, field=field, value_text="A"
            )
            for field in (self.generic, self.case)
        ]

    def freeze_db_only(self):
        PartnerProgramProject.objects.filter(pk=self.link.pk).update(submitted=True)
        self.assertFalse(self.link.submitted)

    def assert_frozen(self, action):
        with self.assertRaisesMessage(ValidationError, FIELD_VALUES_FROZEN_MESSAGE):
            action()

    def test_unchanged_values_validate_and_save_with_pending_parent_submission(self):
        self.link.submitted = True
        for value in self.values:
            with self.subTest(field=value.field.name):
                value.full_clean()
                value.save()
                value.refresh_from_db()
                self.assertEqual(value.value_text, "A")

    def test_unchanged_values_validate_and_save_on_persisted_submitted_parent(self):
        self.freeze_db_only()
        for value in self.values:
            with self.subTest(field=value.field.name):
                value.full_clean()
                value.save()
                value.refresh_from_db()
                self.assertEqual(value.value_text, "A")

    def test_api_still_rejects_identical_put_after_submission(self):
        self.freeze_db_only()
        client = APIClient()
        client.force_authenticate(self.link.project.leader)
        data = [
            {"field_id": value.field_id, "value_text": value.value_text}
            for value in self.values
        ]
        for url in (
            f"/programs/partner-program-projects/{self.link.pk}/fields/",
            f"/projects/{self.link.project_id}/program-fields/",
        ):
            with self.subTest(url=url):
                response = client.put(url, data, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(FIELD_VALUES_FROZEN_MESSAGE, str(response.data))
        self.assertCountEqual(
            list(self.link.field_values.values_list("value_text", flat=True)), ["A", "A"]
        )

    def test_changed_value_uses_db_freeze_despite_stale_parent(self):
        self.freeze_db_only()
        for value in self.values:
            value.value_text = "B"
            with self.subTest(field=value.field.name):
                self.assert_frozen(value.full_clean)
                self.assert_frozen(value.save)
                value.refresh_from_db()
                self.assertEqual(value.value_text, "A")

    def test_pending_submission_does_not_get_lost_during_case_save_lock(self):
        self.link.submitted = True
        for value in self.values:
            value.value_text = "B"
            with self.subTest(field=value.field.name):
                self.assert_frozen(value.full_clean)
                self.assert_frozen(value.save)

    def test_changing_field_is_a_mutation_even_with_same_text(self):
        self.freeze_db_only()
        other = create_program_field(self.program)
        for value in self.values:
            with self.subTest(field=value.field.name):
                value.field = other
                self.assert_frozen(value.full_clean)

    def test_moving_value_out_of_frozen_source_link_is_a_mutation(self):
        self.freeze_db_only()
        other = create_program_project(self.program)
        for value in self.values:
            value.program_project = other
            with self.subTest(field=value.field.name):
                self.assert_frozen(value.full_clean)
                self.assert_frozen(value.save)

    def test_moving_value_into_frozen_target_link_is_a_mutation(self):
        other = create_program_project(self.program, submitted=True)
        for value in self.values:
            value.program_project = other
            with self.subTest(field=value.field.name):
                self.assert_frozen(value.full_clean)

    def test_new_values_on_frozen_link_are_rejected(self):
        self.freeze_db_only()
        PartnerProgramFieldValue.objects.filter(program_project=self.link).delete()
        for field in (self.generic, self.case):
            value = PartnerProgramFieldValue(
                program_project=self.link, field=field, value_text="A"
            )
            with self.subTest(field=field.name):
                self.assert_frozen(value.full_clean)
                self.assert_frozen(value.save)
        self.assertFalse(self.link.field_values.exists())

    def test_same_pk_does_not_make_changed_text_unchanged(self):
        value = self.values[0]
        PartnerProgramFieldValue.objects.filter(pk=value.pk).update(value_text="B")
        self.freeze_db_only()
        self.assert_frozen(value.full_clean)

    def test_noncompetitive_submission_does_not_freeze_generic_or_case_values(self):
        self.program.is_competitive = False
        self.program.save(update_fields=["is_competitive"])
        self.link.submitted = True
        self.link.save(update_fields=["submitted"])
        for value in self.values:
            value.value_text = "B"
            value.full_clean()
            value.save()
            value.refresh_from_db()
            self.assertEqual(value.value_text, "B")

    def test_unchanged_case_still_runs_case_option_validation(self):
        value = self.values[1]
        PartnerProgramFieldValue.objects.filter(pk=value.pk).update(value_text="stale")
        value.refresh_from_db()
        self.freeze_db_only()
        with self.assertRaisesMessage(
            ValidationError, "Выбранный кейс больше недоступен"
        ):
            value.full_clean()
