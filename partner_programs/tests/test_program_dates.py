from datetime import timedelta

from django.forms import modelform_factory
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.admin import PartnerProgramAdmin
from partner_programs.models import PartnerProgram
from partner_programs.program_dates import DATE_FIELDS
from partner_programs.tests.helpers import create_partner_program, create_user


class ProgramDatesTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.program = create_partner_program(
            datetime_started=self.now + timedelta(days=1),
            datetime_registration_ends=self.now + timedelta(days=10),
            datetime_finished=self.now + timedelta(days=30),
        )
        self.manager = create_user()
        self.program.managers.add(self.manager)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def patch_dates(self, **changes):
        self.program.refresh_from_db()
        return self.client.patch(
            f"/programs/{self.program.pk}/management/settings/dates/",
            {"expected_updated_at": self.program.datetime_updated, **changes},
            format="json",
        )

    def admin_form(self, **changes):
        self.program.refresh_from_db()
        form_class = modelform_factory(
            PartnerProgram,
            form=PartnerProgramAdmin.PartnerProgramAdminForm,
            fields=("name", "city", "draft", *DATE_FIELDS),
        )
        values = {
            key: getattr(self.program, key)
            for key in ("name", "city", "draft", *DATE_FIELDS)
        }
        values.update(changes)
        for key in DATE_FIELDS:
            if values.get(key) is not None:
                values[key] = values[key].isoformat(timespec="seconds")
        return form_class(data=values, instance=self.program)

    def test_api_rejects_invalid_partial_dates_without_saving(self):
        original = self.program.datetime_finished
        for finish in (self.program.datetime_started, self.now):
            with self.subTest(finish=finish):
                response = self.patch_dates(datetime_finished=finish)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("datetime_finished", response.data)
                self.program.refresh_from_db()
                self.assertEqual(self.program.datetime_finished, original)
        response = self.patch_dates(
            datetime_registration_ends=original + timedelta(days=1)
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("datetime_registration_ends", response.data)

    def test_api_and_admin_allow_registration_after_start_until_program_end(self):
        for registration in (
            self.program.datetime_started + timedelta(days=1),
            self.program.datetime_finished,
        ):
            with self.subTest(registration=registration):
                form = self.admin_form(datetime_registration_ends=registration)
                self.assertTrue(form.is_valid(), form.errors)
                response = self.patch_dates(datetime_registration_ends=registration)
                self.assertEqual(response.status_code, 200, response.data)

    def test_draft_can_be_incomplete_but_known_dates_must_agree(self):
        self.program.draft = True
        self.program.save()
        response = self.patch_dates(datetime_finished=None)
        self.assertEqual(response.status_code, 200, response.data)
        form = self.admin_form(datetime_started=None, datetime_registration_ends=None)
        self.assertTrue(form.is_valid(), form.errors)
        response = self.patch_dates(datetime_finished=self.now)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("datetime_finished", response.data)

    def test_published_dates_cannot_be_cleared_in_either_interface(self):
        for field in (
            "datetime_started",
            "datetime_finished",
            "datetime_registration_ends",
        ):
            with self.subTest(field=field):
                response = self.patch_dates(**{field: None})
                self.assertEqual(response.status_code, 400, response.data)
                form = self.admin_form(**{field: None})
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_admin_rejects_same_invalid_order_as_api(self):
        form = self.admin_form(datetime_finished=self.now)
        self.assertFalse(form.is_valid())
        self.assertIn("datetime_finished", form.errors)
        self.assertIn("datetime_registration_ends", form.errors)

    def test_reopening_requires_confirmation_in_both_interfaces(self):
        self.program.datetime_registration_ends = self.now - timedelta(days=1)
        self.program.save()
        registration = self.now + timedelta(days=2)
        response = self.patch_dates(datetime_registration_ends=registration)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "reopen_confirmation_required")
        form = self.admin_form(datetime_registration_ends=registration)
        self.assertFalse(form.is_valid())
        self.assertIn("confirm_reopen", form.errors)
        form = self.admin_form(
            datetime_registration_ends=registration, confirm_reopen=True
        )
        self.assertTrue(form.is_valid(), form.errors)
        response = self.patch_dates(
            datetime_registration_ends=registration, confirm_reopen=True
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_admin_can_edit_a_frontend_program_without_city(self):
        self.program.city = ""
        self.program.save()
        form = self.admin_form(datetime_finished=self.now + timedelta(days=35))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.program.refresh_from_db()
        self.assertEqual(self.program.city, "")

    def test_past_registration_is_valid_when_editing_existing_program(self):
        self.program.datetime_started = self.now - timedelta(days=30)
        self.program.save()
        registration = self.now - timedelta(days=1)
        response = self.patch_dates(datetime_registration_ends=registration)
        self.assertEqual(response.status_code, 200, response.data)
        form = self.admin_form(datetime_finished=self.now + timedelta(days=5))
        self.assertTrue(form.is_valid(), form.errors)

    def test_metadata_edit_does_not_block_legacy_inconsistent_calendar(self):
        self.program.datetime_finished = self.now
        self.program.save()
        form = self.admin_form(name="Исправленное название")
        self.assertTrue(form.is_valid(), form.errors)

    def test_dates_validation_does_not_grant_access(self):
        for actor, status in ((create_user(), 403), (None, 401)):
            with self.subTest(status=status):
                self.client.force_authenticate(actor)
                response = self.patch_dates(datetime_finished=self.now)
                self.assertEqual(response.status_code, status, response.data)
