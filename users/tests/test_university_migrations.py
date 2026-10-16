from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class UniversityProductionMigrationTests(TransactionTestCase):
    before = [("users", "0062_customuser_modal_acknowledgements")]
    after = [("users", "0065_expand_university_directory")]

    def test_existing_education_survives_directory_migrations_unchanged(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        try:
            apps = executor.loader.project_state(self.before).apps
            user = apps.get_model("users", "CustomUser").objects.create(
                email="university-migration@example.com",
                password="!",
                birthday=date(2000, 1, 1),
            )
            education = apps.get_model("users", "UserEducation")
            for name in ("  Старое название Ё-вуза  ", "Школа №42", "Колледж"):
                education.objects.create(
                    user_id=user.pk,
                    organization_name=name,
                    description="Прежнее направление",
                    entry_year=2010,
                    completion_year=2015,
                    education_level="legacy level",
                    education_status="legacy status",
                )
            original = list(education.objects.order_by("pk").values())

            executor = MigrationExecutor(connection)
            executor.migrate(self.after)
            apps = executor.loader.project_state(self.after).apps
            self.assertEqual(
                list(
                    apps.get_model("users", "UserEducation")
                    .objects.order_by("pk")
                    .values()
                ),
                original,
            )
            self.assertEqual(
                apps.get_model("users", "University")
                .objects.filter(is_active=True)
                .count(),
                1337,
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
