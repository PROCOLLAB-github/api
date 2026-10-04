import importlib
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from users.models import University, UserEducation
from .helpers import build_user


class UniversityImportTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "universities.json"
        self.document = {
            "source_url": "https://example.org/universities/",
            "checked_at": "2026-10-04",
            "universities": [
                {"source_id": "test:one", "name": "Новый вуз", "aliases": "НВУ"}
            ],
        }
        self.path.write_text(json.dumps(self.document), encoding="utf-8")

    def test_import_is_idempotent_and_preserves_admin_edits(self):
        call_command("import_universities", str(self.path), stdout=StringIO())
        university = University.objects.get(source_id="test:one")
        university.name = "Ручное название"
        university.is_active = False
        university.save()
        call_command("import_universities", str(self.path), stdout=StringIO())
        university.refresh_from_db()
        self.assertEqual(university.name, "Ручное название")
        self.assertFalse(university.is_active)
        self.assertEqual(University.objects.filter(source_id="test:one").count(), 1)
        call_command(
            "import_universities", str(self.path), update_existing=True, stdout=StringIO()
        )
        university.refresh_from_db()
        self.assertEqual(university.name, "Новый вуз")
        self.assertIn("нву", university.search_text)
        self.assertFalse(university.is_active)

    def test_invalid_file_never_partially_imports(self):
        self.document["universities"].append(
            {"source_id": "test:invalid", "name": "я" * 256}
        )
        self.path.write_text(json.dumps(self.document), encoding="utf-8")
        with self.assertRaises(CommandError):
            call_command("import_universities", str(self.path), stdout=StringIO())
        self.assertFalse(University.objects.filter(source_id="test:one").exists())

    def test_seed_preserves_existing_directory_and_user_education(self):
        user = build_user(email="seed-legacy@example.com")
        education = UserEducation.objects.create(
            user=user, organization_name="Название 1995 года"
        )
        snapshot = json.loads(
            (
                Path(__file__).resolve().parent.parent
                / "data"
                / "universities_20261004.json"
            ).read_text(encoding="utf-8")
        )
        source_id = snapshot["universities"][0]["source_id"]
        university = University.objects.get(source_id=source_id)
        university.name = "Изменено администратором"
        university.is_active = False
        university.save()
        migration = importlib.import_module(
            "users.migrations.0063_seed_university_directory"
        )
        migration.seed_universities(apps, SimpleNamespace(connection=connection))
        university.refresh_from_db()
        education.refresh_from_db()
        self.assertEqual(university.name, "Изменено администратором")
        self.assertFalse(university.is_active)
        self.assertEqual(education.organization_name, "Название 1995 года")
        self.assertEqual(len(snapshot["universities"]), 461)
