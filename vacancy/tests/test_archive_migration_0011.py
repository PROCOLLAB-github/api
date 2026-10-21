from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from vacancy.tests.helpers import create_project


class VacancyArchiveMigrationTests(TransactionTestCase):
    def test_existing_inactive_vacancies_remain_archived_without_changing_history(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [("vacancy", "0010_vacancy_city")]
        after = [("vacancy", "0011_vacancy_resume_on_publish")]
        try:
            executor.migrate(before)
            old_apps = executor.loader.project_state(before).apps
            OldVacancy = old_apps.get_model("vacancy", "Vacancy")
            closed_at = timezone.now()
            records = []
            for draft, active in [(False, True), (False, False), (True, False)]:
                project = create_project(draft=draft)
                vacancy = OldVacancy.objects.create(
                    project_id=project.pk,
                    role="Существующая вакансия",
                    is_active=active,
                    datetime_closed=None if active else closed_at,
                )
                records.append((vacancy.pk, active, vacancy.datetime_closed))

            executor = MigrationExecutor(connection)
            executor.migrate(after)
            NewVacancy = executor.loader.project_state(after).apps.get_model(
                "vacancy", "Vacancy"
            )
            for pk, active, date in records:
                vacancy = NewVacancy.objects.get(pk=pk)
                self.assertEqual(vacancy.is_active, active)
                self.assertEqual(vacancy.datetime_closed, date)
                self.assertFalse(vacancy.resume_on_publish)
        finally:
            MigrationExecutor(connection).migrate(latest)
