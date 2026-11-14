from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram
from partner_programs.tests.helpers import create_partner_program, create_user


class ProgramCreationAdminTests(TestCase):
    def setUp(self):
        self.admin = create_user(is_staff=True, is_superuser=True, is_active=True)
        self.client.force_login(self.admin)
        self.url = reverse("admin:partner_programs_partnerprogram_create_draft")

    def test_admin_creates_same_accelerator_as_api_and_retry_is_idempotent(self):
        previous = create_partner_program(program_format="noncompetitive")
        data = {
            "name": "Акселератор проектов",
            "format": "accelerator",
            "idempotency_key": str(uuid4()),
        }
        page = self.client.get(self.url)
        self.assertContains(page, "Акселератор")
        self.assertContains(page, "Кейс-чемпионат")
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        program = PartnerProgram.objects.get(name=data["name"])
        self.assertEqual(program.program_format, "accelerator")
        self.assertFalse(program.is_competitive)
        self.assertEqual(program.solution_storage_mode, "legacy_project")
        self.assertTrue(program.draft)
        self.assertTrue(program.managers.filter(pk=self.admin.pk).exists())
        api = APIClient()
        api.force_authenticate(self.admin)
        retry = api.post("/programs/drafts/", data, format="json")
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(retry.data["id"], program.pk)
        self.assertEqual(PartnerProgram.objects.filter(name=data["name"]).count(), 1)
        previous.refresh_from_db()
        self.assertEqual(previous.program_format, "noncompetitive")

    def test_admin_requires_creation_permission_and_valid_format(self):
        without_permission = create_user(is_staff=True, is_active=True)
        self.client.force_login(without_permission)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.post(
                self.url,
                {
                    "name": "Новая",
                    "format": "accelerator",
                    "idempotency_key": str(uuid4()),
                },
            ).status_code,
            403,
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            self.url,
            {"name": "Новая", "format": "unknown", "idempotency_key": str(uuid4())},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PartnerProgram.objects.filter(name="Новая").exists())
