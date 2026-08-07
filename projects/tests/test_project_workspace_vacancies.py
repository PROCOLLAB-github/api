from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from projects.tests.helpers import create_project, create_user
from vacancy.models import Vacancy
from vacancy.tests.helpers import (
    create_skill,
    create_vacancy,
    create_vacancy_response,
)


class ProjectWorkspaceVacanciesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="workspace-vacancies-leader")

    def get_workspace(self, project):
        self.client.force_authenticate(user=self.leader)
        return self.client.get(f"/projects/{project.pk}/workspace/")

    def test_workspace_detail_returns_only_current_project_vacancies(self):
        project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        foreign_project = create_project()
        active = create_vacancy(project=project, role="Активная", is_active=True)
        inactive = create_vacancy(
            project=project,
            role="Неактивная",
            is_active=False,
        )
        old = create_vacancy(project=project, role="Старая", is_active=True)
        Vacancy.objects.filter(pk=old.pk).update(
            datetime_created=timezone.now() - timedelta(days=120)
        )
        create_vacancy(project=foreign_project, role="Чужая", is_active=True)

        response = self.get_workspace(project)

        self.assertEqual(response.status_code, 200)
        vacancies = {item["id"]: item for item in response.data["vacancies"]}
        self.assertEqual(set(vacancies), {active.pk, inactive.pk, old.pk})
        self.assertTrue(vacancies[active.pk]["is_active"])
        self.assertFalse(vacancies[inactive.pk]["is_active"])
        self.assertIn(old.pk, vacancies)

    def test_workspace_detail_returns_empty_vacancy_list(self):
        project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )

        response = self.get_workspace(project)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["vacancies"], [])

    def test_workspace_vacancy_reuses_legacy_short_contract(self):
        project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        vacancy = create_vacancy(
            project=project,
            role="Backend-разработчик",
            is_active=False,
        )
        skill = create_skill(name="Python")
        vacancy.required_skills.create(skill=skill)
        create_vacancy_response(vacancy=vacancy, is_approved=None)
        create_vacancy_response(vacancy=vacancy, is_approved=False)

        response = self.get_workspace(project)

        self.assertEqual(response.status_code, 200)
        item = response.data["vacancies"][0]
        self.assertEqual(
            set(item),
            {
                "id",
                "role",
                "specialization",
                "required_skills",
                "description",
                "project",
                "is_active",
                "datetime_closed",
                "response_count",
                "date_create_time",
            },
        )
        self.assertEqual(item["project"], project.pk)
        self.assertEqual(item["required_skills"][0]["id"], skill.pk)
        self.assertEqual(item["response_count"], 1)

    def test_workspace_fields_and_access_flags_remain_available(self):
        project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        create_vacancy(project=project)

        response = self.get_workspace(project)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_user_role"], "leader")
        self.assertTrue(response.data["can_edit"])
        self.assertTrue(response.data["can_use_in_application"])
        self.assertIn("activities", response.data)
        self.assertIn("collaborators", response.data)
        self.assertIn("vacancies", response.data)

    def test_workspace_vacancies_do_not_create_n_plus_one_queries(self):
        def capture_for(vacancy_count):
            project = create_project(
                leader=self.leader,
                draft=True,
                is_public=False,
            )
            for index in range(vacancy_count):
                vacancy = create_vacancy(
                    project=project,
                    role=f"Vacancy {index}",
                )
                vacancy.required_skills.create(skill=create_skill(name=f"Skill {index}"))
                create_vacancy_response(vacancy=vacancy, is_approved=None)

            self.client.force_authenticate(user=self.leader)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(f"/projects/{project.pk}/workspace/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data["vacancies"]), vacancy_count)
            return len(queries)

        one_vacancy_queries = capture_for(1)
        five_vacancies_queries = capture_for(5)

        self.assertLessEqual(five_vacancies_queries, one_vacancy_queries)
