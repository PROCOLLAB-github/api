import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from industries.models import Industry
from industries.reference_data import REACT_DEV_INDUSTRY_NAMES
from industries.tests.helpers import create_user
from projects.models import Project


class ReactDevIndustrySeedTests(TestCase):
    def run_seed(self, *extra_args, confirm=True):
        args = list(extra_args)
        if confirm:
            args.append("--confirm-react-dev")
        stdout = io.StringIO()
        with override_settings(ALLOW_REACT_DEV_DEMO_SEED=True):
            call_command("seed_react_dev_industries", *args, stdout=stdout)
        return stdout.getvalue()

    def test_seed_is_disabled_by_default_before_any_write(self):
        with self.assertRaisesMessage(CommandError, "отключено"):
            call_command(
                "seed_react_dev_industries",
                "--confirm-react-dev",
            )

        self.assertFalse(Industry.objects.exists())

    def test_seed_requires_explicit_react_dev_confirmation(self):
        with self.assertRaisesMessage(CommandError, "--confirm-react-dev"):
            self.run_seed(confirm=False)

        self.assertFalse(Industry.objects.exists())

    def test_seed_creates_complete_reference_and_preserves_other_rows(self):
        custom = Industry.objects.create(name="Локальная тестовая отрасль")

        output = self.run_seed()

        self.assertEqual(
            set(
                Industry.objects.filter(name__in=REACT_DEV_INDUSTRY_NAMES).values_list(
                    "name",
                    flat=True,
                )
            ),
            set(REACT_DEV_INDUSTRY_NAMES),
        )
        self.assertTrue(Industry.objects.filter(pk=custom.pk).exists())
        self.assertIn(f"Создано отраслей: {len(REACT_DEV_INDUSTRY_NAMES)}", output)

    def test_repeated_seed_does_not_create_duplicates(self):
        self.run_seed()
        first_count = Industry.objects.count()

        output = self.run_seed()

        self.assertEqual(Industry.objects.count(), first_count)
        self.assertIn("Создано отраслей: 0", output)
        self.assertIn(f"Уже существовало: {first_count}", output)

    def test_dry_run_rolls_back_created_industries(self):
        output = self.run_seed("--dry-run")

        self.assertFalse(Industry.objects.exists())
        self.assertIn("созданные записи не сохранены", output)


class ReactDevIndustryProjectLifecycleTests(TestCase):
    def setUp(self):
        with override_settings(ALLOW_REACT_DEV_DEMO_SEED=True):
            call_command(
                "seed_react_dev_industries",
                "--confirm-react-dev",
                stdout=io.StringIO(),
            )
        self.user = create_user(prefix="react-dev-industry-project")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_seeded_industry_supports_draft_edit_and_publication(self):
        industries_response = self.client.get("/industries/")
        self.assertEqual(industries_response.status_code, 200)
        self.assertEqual(len(industries_response.data), len(REACT_DEV_INDUSTRY_NAMES))
        industry_id = industries_response.data[0]["id"]

        create_response = self.client.post("/projects/workspace/", {}, format="json")
        self.assertEqual(create_response.status_code, 201)
        project_id = create_response.data["id"]

        draft_response = self.client.patch(
            f"/projects/{project_id}/workspace/",
            {
                "name": "Черновик проекта",
                "industry": industry_id,
                "draft": True,
                "is_public": False,
            },
            format="json",
        )
        self.assertEqual(draft_response.status_code, 200)
        self.assertEqual(draft_response.data["industry"]["id"], industry_id)

        edit_response = self.client.get(f"/projects/{project_id}/workspace/")
        self.assertEqual(edit_response.status_code, 200)
        self.assertEqual(edit_response.data["industry"]["id"], industry_id)

        publish_response = self.client.patch(
            f"/projects/{project_id}/workspace/",
            {
                "region": "Москва",
                "description": "Описание проекта",
                "problem": "Описание проблемы",
                "target_audience": "Целевая аудитория",
                "cover_image_address": "https://example.com/project-cover.png",
                "draft": False,
                "is_public": True,
            },
            format="json",
        )
        self.assertEqual(publish_response.status_code, 200)
        self.assertEqual(publish_response.data["industry"]["id"], industry_id)

        project = Project.objects.get(pk=project_id)
        self.assertEqual(project.industry_id, industry_id)
        self.assertFalse(project.draft)
        self.assertTrue(project.is_public)
