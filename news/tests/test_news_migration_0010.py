from importlib import import_module
import unittest

from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase


class NewsMigration0010MetadataTests(SimpleTestCase):
    def test_migration_is_non_atomic(self):
        migration = import_module("news.migrations.0010_news_audience_newscomment")

        self.assertIs(migration.Migration.atomic, False)

    def test_runpython_does_not_reintroduce_atomic_transaction(self):
        migration = import_module("news.migrations.0010_news_audience_newscomment")
        run_python_operations = [
            operation
            for operation in migration.Migration.operations
            if isinstance(operation, migrations.RunPython)
        ]

        self.assertEqual(len(run_python_operations), 1)
        self.assertIsNone(run_python_operations[0].atomic)


@unittest.skipUnless(
    connection.vendor == "postgresql",
    "PostgreSQL-only regression for pending trigger events during migration 0010.",
)
class NewsMigration0010PostgreSQLTests(TransactionTestCase):
    migrate_from = [("news", "0009_news_pin")]
    migrate_to = [("news", "0010_news_audience_newscomment")]

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        self.apps = self.executor.loader.project_state(self.migrate_from).apps

    def tearDown(self):
        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        super().tearDown()

    def test_applies_after_updating_existing_news_rows(self):
        ContentType = self.apps.get_model("contenttypes", "ContentType")
        News = self.apps.get_model("news", "News")
        project_content_type, _ = ContentType.objects.get_or_create(
            app_label="projects",
            model="project",
        )
        program_content_type, _ = ContentType.objects.get_or_create(
            app_label="partner_programs",
            model="partnerprogram",
        )

        News.objects.create(
            content_type=project_content_type,
            object_id=1,
            text="Project news",
        )
        News.objects.create(
            content_type=program_content_type,
            object_id=1,
            text="Program news",
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        migrated_apps = self.executor.loader.project_state(self.migrate_to).apps
        MigratedNews = migrated_apps.get_model("news", "News")

        self.assertEqual(
            MigratedNews.objects.get(content_type_id=project_content_type.id).audience,
            "platform",
        )
        self.assertEqual(
            MigratedNews.objects.get(content_type_id=program_content_type.id).audience,
            "program_participants",
        )
