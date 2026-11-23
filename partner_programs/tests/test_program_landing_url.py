from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)
from partner_programs.program_dates import DATE_FIELDS


LANDING_URL = "https://example.org/program?source=procollab"
INVALID_LANDING_URLS = ("example.org/program", "ftp://example.org/program", "http://")


class ProgramLandingUrlTests(TestCase):
    def setUp(self):
        self.program = create_partner_program(
            registration_link="https://example.org/register",
            presentation_address="https://example.org/presentation",
        )
        self.manager = create_user(is_active=True)
        self.program.managers.add(self.manager)
        self.member = create_program_member(
            self.program, user=create_user(is_active=True)
        ).user
        self.detail_url = f"/programs/{self.program.pk}/"
        self.management_url = self.detail_url + "management/"
        self.settings_url = self.management_url + "settings/basic/"
        self.api = APIClient()

    def patch_landing_url(self, value):
        self.program.refresh_from_db()
        return self.api.patch(
            self.settings_url,
            {"landing_url": value, "expected_updated_at": self.program.datetime_updated},
            format="json",
        )

    def test_manager_can_set_and_clear_the_separate_link(self):
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.api.get(self.management_url).data["landing_url"], "")
        for value in (LANDING_URL, ""):
            with self.subTest(value=value):
                response = self.patch_landing_url(value)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["landing_url"], value)
                self.assertEqual(self.api.get(self.management_url).data["landing_url"], value)
                self.program.refresh_from_db()
                self.assertEqual(self.program.landing_url, value)
                self.assertEqual(self.program.registration_link, "https://example.org/register")
                self.assertEqual(self.program.presentation_address, "https://example.org/presentation")

    def test_only_manager_can_edit_and_api_rejects_invalid_links(self):
        other_manager = create_user(is_active=True)
        create_partner_program().managers.add(other_manager)
        for user in (self.member, other_manager):
            with self.subTest(user=user):
                self.api.force_authenticate(user)
                self.assertEqual(self.patch_landing_url(LANDING_URL).status_code, 403)
                self.assertEqual(self.api.get(self.management_url).status_code, 403)
        self.api.force_authenticate(self.manager)
        for value in INVALID_LANDING_URLS:
            with self.subTest(value=value):
                response = self.patch_landing_url(value)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("landing_url", response.data)
        self.program.refresh_from_db()
        self.assertEqual(self.program.landing_url, "")

    def test_visible_detail_exposes_the_link_with_or_without_membership(self):
        self.assertEqual(self.api.get(self.detail_url).data["landing_url"], "")
        self.program.landing_url = LANDING_URL
        self.program.save(update_fields=["landing_url"])
        for actor in (None, self.member):
            with self.subTest(actor=actor):
                self.api.force_authenticate(actor)
                response = self.api.get(self.detail_url)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["landing_url"], LANDING_URL)
        self.program.draft = True
        self.program.save(update_fields=["draft"])
        for actor in (None, self.member):
            with self.subTest(actor=actor):
                self.api.force_authenticate(actor)
                response = self.api.get(self.detail_url)
                self.assertEqual(response.status_code, 404, response.data)
                self.assertNotIn("landing_url", response.data)

    def test_admin_manager_edits_link_using_same_validation(self):
        self.program.draft = True
        self.program.save(update_fields=["draft"])
        self.manager.is_staff = True
        self.manager.save(update_fields=["is_staff"])
        self.manager.groups.add(Group.objects.get_or_create(name="Руководитель программы")[0])
        self.manager.user_permissions.add(Permission.objects.get(codename="change_partnerprogram"))
        self.client.force_login(self.manager)
        url = reverse("admin:partner_programs_partnerprogram_change", args=[self.program.pk])
        page = self.client.get(url)
        self.assertContains(page, "Ссылка «Подробнее»")
        payload = {
            "name": self.program.name,
            "tag": self.program.tag,
            "city": self.program.city,
            "description": self.program.description,
            "draft": "on",
            "projects_availability": self.program.projects_availability,
            "registration_link": self.program.registration_link,
            "presentation_address": self.program.presentation_address,
            "max_project_rates": self.program.max_project_rates,
            "data_schema": '{"name": {"name": "Имя"}}',
            "project_sections": "{}",
            "managers": [self.manager.pk],
        }
        for field in DATE_FIELDS:
            value = getattr(self.program, field)
            if value is not None:
                value = timezone.localtime(value)
                payload[f"{field}_0"] = value.strftime("%Y-%m-%d")
                payload[f"{field}_1"] = value.strftime("%H:%M:%S")
        for inline in page.context["inline_admin_formsets"]:
            prefix = inline.formset.prefix
            payload[f"{prefix}-TOTAL_FORMS"] = 0
            payload[f"{prefix}-INITIAL_FORMS"] = 0
        for value in INVALID_LANDING_URLS:
            with self.subTest(value=value):
                response = self.client.post(url, {**payload, "landing_url": value})
                self.assertContains(response, "Укажите корректную ссылку с http:// или https://.")
        for value in (LANDING_URL, ""):
            with self.subTest(value=value):
                response = self.client.post(url, {**payload, "landing_url": value})
                self.assertEqual(response.status_code, 302)
                self.program.refresh_from_db()
                self.assertEqual(self.program.landing_url, value)
