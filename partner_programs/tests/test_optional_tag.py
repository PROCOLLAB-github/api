"""Пустой тег допустим в модели, админке и настройках организатора."""

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram
from partner_programs.tests.helpers import create_user


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class OptionalProgramTagTests(TestCase):
    def setUp(self):
        self.admin = create_user(is_staff=True, is_superuser=True, is_active=True)
        self.client.force_login(self.admin)
        self.url = reverse("admin:partner_programs_partnerprogram_add")

    def payload(self):
        page = self.client.get(self.url)
        self.assertFalse(page.context["adminform"].form.fields["tag"].required)
        data = {
            "name": "Программа без тега", "tag": "", "description": "Описание", "city": "Москва",
            "projects_availability": "all_users", "data_schema": '{"extra": {"name": "Поле"}}',
            "draft": "on", "_save": "Сохранить",
        }
        for inline in page.context["inline_admin_formsets"]:
            prefix = inline.formset.prefix
            data.update({f"{prefix}-TOTAL_FORMS": 0, f"{prefix}-INITIAL_FORMS": 0})
        return data

    def test_create_in_admin_without_tag_and_edit_through_frontend_settings(self):
        response = self.client.post(self.url, self.payload())
        errors = response.context["adminform"].form.errors if response.status_code == 200 else None
        self.assertEqual(response.status_code, 302, errors)
        program = PartnerProgram.objects.get(name="Программа без тега")
        self.assertEqual(program.tag, "")
        program.full_clean()
        self.assertTrue(program.managers.filter(pk=self.admin.pk).exists())
        api = APIClient()
        api.force_authenticate(self.admin)
        saved = api.patch(
            f"/programs/{program.pk}/management/settings/basic/",
            {"tag": "", "expected_updated_at": program.datetime_updated.isoformat()}, format="json",
        )
        self.assertEqual(saved.status_code, 200, saved.data)

    def test_existing_nonempty_tag_remains_unchanged(self):
        data = self.payload()
        data["tag"] = "существующий-тег"
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        program = PartnerProgram.objects.get(name=data["name"])
        self.assertEqual(program.tag, data["tag"])
