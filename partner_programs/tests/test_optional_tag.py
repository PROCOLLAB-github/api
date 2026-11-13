"""Пустой тег допустим в модели, админке и настройках организатора."""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram
from partner_programs.tests.helpers import create_user
from project_rates.program_experts import can_evaluate_program
from project_rates.tests.helpers import create_rate_user


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class OptionalProgramTagTests(TestCase):
    def setUp(self):
        self.admin = create_user(is_staff=True, is_superuser=True, is_active=True)
        self.client.force_login(self.admin)
        self.url = reverse("admin:partner_programs_partnerprogram_add")

    def payload(self):
        page = self.client.get(self.url)
        self.assertFalse(page.context["adminform"].form.fields["tag"].required)
        data = {
            "name": "Программа без тега",
            "tag": "",
            "description": "Описание",
            "city": "Москва",
            "projects_availability": "all_users",
            "data_schema": '{"extra": {"name": "Поле"}}',
            "draft": "on",
            "_save": "Сохранить",
        }
        for inline in page.context["inline_admin_formsets"]:
            prefix = inline.formset.prefix
            data.update({f"{prefix}-TOTAL_FORMS": 0, f"{prefix}-INITIAL_FORMS": 0})
        return data

    def test_create_in_admin_without_tag_and_edit_through_frontend_settings(self):
        response = self.client.post(self.url, self.payload())
        errors = (
            response.context["adminform"].form.errors
            if response.status_code == 200
            else None
        )
        self.assertEqual(response.status_code, 302, errors)
        program = PartnerProgram.objects.get(name="Программа без тега")
        self.assertEqual(program.tag, "")
        program.full_clean()
        self.assertTrue(program.managers.filter(pk=self.admin.pk).exists())
        api = APIClient()
        api.force_authenticate(self.admin)
        saved = api.patch(
            f"/programs/{program.pk}/management/settings/basic/",
            {"tag": "", "expected_updated_at": program.datetime_updated.isoformat()},
            format="json",
        )
        self.assertEqual(saved.status_code, 200, saved.data)

    def test_existing_nonempty_tag_remains_unchanged(self):
        data = self.payload()
        data["tag"] = "существующий-тег"
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        program = PartnerProgram.objects.get(name=data["name"])
        self.assertEqual(program.tag, data["tag"])

    def test_admin_allows_empty_legacy_schema_when_adding_a_manager(self):
        data = self.payload()
        data["data_schema"] = "{}"
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        program = PartnerProgram.objects.get(name=data["name"])
        now = timezone.now().replace(microsecond=0)
        program.draft = False
        program.datetime_started = now - timezone.timedelta(days=1)
        program.datetime_registration_ends = now + timezone.timedelta(days=1)
        program.datetime_project_submission_ends = now + timezone.timedelta(days=1)
        program.datetime_evaluation_ends = now + timezone.timedelta(days=2)
        program.datetime_finished = now + timezone.timedelta(days=3)
        program.save()
        organizer = create_rate_user(prefix="empty-schema-manager")
        self.url = reverse(
            "admin:partner_programs_partnerprogram_change", args=[program.pk]
        )
        data = self.payload()
        data.pop("draft")
        data["data_schema"] = "{}"
        data["managers"] = [self.admin.pk, organizer.pk]
        for field in (
            "datetime_started",
            "datetime_registration_ends",
            "datetime_project_submission_ends",
            "datetime_evaluation_ends",
            "datetime_finished",
        ):
            value = timezone.localtime(getattr(program, field))
            data[field + "_0"] = value.strftime("%Y-%m-%d")
            data[field + "_1"] = value.strftime("%H:%M:%S")
        response = self.client.post(self.url, data)
        errors = (
            response.context["adminform"].form.errors
            if response.status_code == 200
            else None
        )
        self.assertEqual(response.status_code, 302, errors)
        program.refresh_from_db()
        organizer.refresh_from_db()
        self.assertEqual(program.data_schema, {})
        self.assertTrue(can_evaluate_program(organizer, program.pk))
        self.assertEqual(organizer.user_type, organizer.MEMBER)
        self.assertFalse(organizer.expert.project_assignments.exists())

    def test_admin_blank_legacy_schema_becomes_an_empty_object(self):
        data = self.payload()
        data["data_schema"] = ""
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(PartnerProgram.objects.get(name=data["name"]).data_schema, {})

    def test_admin_manager_selection_uses_live_evaluation_access(self):
        organizer = create_rate_user(prefix="admin-added-organizer")
        data = self.payload()
        data["managers"] = [organizer.pk]
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        program = PartnerProgram.objects.get(name=data["name"])
        self.assertFalse(can_evaluate_program(organizer, program.pk))

        now = timezone.now()
        program.draft = False
        program.datetime_started = now
        program.datetime_registration_ends = now + timezone.timedelta(days=1)
        program.datetime_finished = now + timezone.timedelta(days=2)
        program.save()
        self.assertTrue(can_evaluate_program(organizer, program.pk))
        self.assertFalse(organizer.expert.programs.exists())

        organizer.expert.programs.add(program)
        program.managers.remove(organizer)
        self.assertTrue(can_evaluate_program(organizer, program.pk))
