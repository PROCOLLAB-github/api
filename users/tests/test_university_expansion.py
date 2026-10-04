import importlib
import json
from datetime import date
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase

from users.models import University, UserEducation
from .helpers import build_user


class UniversityExpansionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        data = Path(__file__).resolve().parent.parent / "data"
        cls.original = json.loads(
            (data / "universities_20261004.json").read_text(encoding="utf-8")
        )
        cls.snapshot_path = data / "universities_20261004_full.json"
        cls.expanded = json.loads(cls.snapshot_path.read_text(encoding="utf-8"))

    def setUp(self):
        self.historical_apps = (
            MigrationExecutor(connection)
            .loader.project_state([("users", "0064_expand_university_directory")])
            .apps
        )
        self.editor = SimpleNamespace(connection=connection)
        self.seed = importlib.import_module(
            "users.migrations.0063_seed_university_directory"
        ).seed_universities
        self.expand = importlib.import_module(
            "users.migrations.0064_expand_university_directory"
        ).expand_universities

    def restore_original_seed(self):
        University.objects.all().delete()
        self.seed(self.historical_apps, self.editor)

    def test_snapshot_has_complete_catalog_and_departmental_supplement(self):
        rows = self.expanded["universities"]
        self.assertEqual(len(rows), 1337)
        self.assertEqual(len({row["source_id"] for row in rows}), 1337)
        self.assertEqual(sum("catalog_id" in row["provenance"] for row in rows), 1229)
        self.assertEqual(sum(row["provenance"]["is_branch"] for row in rows), 534)
        self.assertEqual(
            {
                row["department"]: row["records"]
                for row in self.expanded["departmental_sources"]
            },
            {
                "Ministry of Defence": 43,
                "FSB": 13,
                "FSIN": 9,
                "MVD": 28,
                "Rosguard": 4,
                "MChS": 7,
                "FSO": 1,
                "SVR": 1,
            },
        )
        self.assertTrue(all(row["source_url"] for row in rows))
        original_codes = {row["source_id"] for row in self.original["universities"]}
        retained_codes = {row["source_id"] for row in rows}
        retired_codes = {row["source_id"] for row in self.expanded["retired_legacy"]}
        self.assertEqual(original_codes - retained_codes, retired_codes)

    def test_full_snapshot_passes_import_validation(self):
        University.objects.all().delete()
        call_command("import_universities", str(self.snapshot_path), stdout=StringIO())
        self.assertEqual(University.objects.count(), 1337)
        self.assertEqual(University.objects.filter(is_active=True).count(), 1337)

    def test_expansion_updates_only_original_seed_and_preserves_education(self):
        self.restore_original_seed()
        old_izhevsk = next(
            row for row in self.original["universities"] if "Ижевская" in row["name"]
        )
        retired = self.expanded["retired_legacy"][0]
        old_name = University.objects.get(source_id=retired["source_id"]).name
        education = UserEducation.objects.create(
            user=build_user(email="expanded-legacy@example.com"),
            organization_name="  " + old_name + "  ",
        )
        self.expand(self.historical_apps, self.editor)
        self.expand(self.historical_apps, self.editor)
        self.assertEqual(University.objects.count(), 1338)
        self.assertEqual(University.objects.filter(is_active=True).count(), 1337)
        self.assertIn(
            "университет",
            University.objects.get(source_id=old_izhevsk["source_id"]).name,
        )
        self.assertFalse(University.objects.get(source_id=retired["source_id"]).is_active)
        successor = University.objects.get(source_id=retired["successor_source_id"])
        self.assertIn(old_name, successor.aliases)
        self.assertIn("зауралья", successor.search_text)
        education.refresh_from_db()
        self.assertEqual(education.organization_name, "  " + old_name + "  ")

    def test_expansion_preserves_each_kind_of_admin_edit(self):
        self.restore_original_seed()
        edits = {
            "name": "Название администратора",
            "full_name": "Полное название администратора",
            "aliases": "Ручное сокращение",
            "city": "Ручной город",
            "source_url": "https://example.org/manual-source/",
            "source_checked_at": date(2026, 10, 1),
            "is_active": False,
        }
        originals = self.original["universities"][: len(edits)]
        expected = []
        for row, (field, value) in zip(originals, edits.items()):
            university = University.objects.get(source_id=row["source_id"])
            setattr(university, field, value)
            university.save()
            expected.append(
                (university.pk, {key: getattr(university, key) for key in edits})
            )
        retired = University.objects.get(
            source_id=self.expanded["retired_legacy"][0]["source_id"]
        )
        retired.aliases = "Исправлено администратором"
        retired.save()
        manual = University.objects.create(name="Вручную добавленный вуз")
        self.expand(self.historical_apps, self.editor)
        for primary_key, fields in expected:
            university = University.objects.get(pk=primary_key)
            with self.subTest(source_id=university.source_id):
                for field, value in fields.items():
                    self.assertEqual(getattr(university, field), value)
        retired.refresh_from_db()
        self.assertTrue(retired.is_active)
        self.assertEqual(retired.aliases, "Исправлено администратором")
        self.assertTrue(University.objects.filter(pk=manual.pk).exists())
