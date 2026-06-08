from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from vacancy.models import Vacancy
from vacancy.tests.helpers import (
    create_project,
    create_skill,
    create_user,
    create_vacancy,
    create_vacancy_response,
    vacancy_payload,
)


class VacancyAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_project_leader_can_create_vacancy(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        skill = create_skill(name="Django")
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/vacancies/",
            vacancy_payload(project, [skill], role="Django developer"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], "Django developer")
        self.assertEqual(response.data["project"]["id"], project.id)
        self.assertEqual(response.data["required_skills"][0]["id"], skill.id)
        self.assertTrue(Vacancy.objects.get(pk=response.data["id"]).is_active)

    def test_user_cannot_create_vacancy_for_foreign_project(self):
        leader = create_user(prefix="leader")
        outsider = create_user(prefix="outsider")
        project = create_project(leader=leader)
        self.client.force_authenticate(outsider)

        response = self.client.post(
            "/vacancies/",
            vacancy_payload(project),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Vacancy.objects.exists())

    def test_vacancy_for_draft_project_is_created_inactive(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader, draft=True)
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/vacancies/",
            vacancy_payload(project),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(Vacancy.objects.get(pk=response.data["id"]).is_active)

    def test_public_list_returns_only_active_vacancies_by_default(self):
        active_vacancy = create_vacancy(role="Active vacancy", is_active=True)
        create_vacancy(role="Inactive vacancy", is_active=False)

        response = self.client.get("/vacancies/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [active_vacancy.id],
        )

    def test_list_can_include_inactive_vacancies_by_filter(self):
        create_vacancy(role="Active vacancy", is_active=True)
        inactive_vacancy = create_vacancy(role="Inactive vacancy", is_active=False)

        response = self.client.get("/vacancies/", {"is_active": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [inactive_vacancy.id],
        )

    def test_list_filters_by_project_role_salary_and_work_conditions(self):
        project = create_project(name="Target project")
        target = create_vacancy(
            project=project,
            role="Python backend",
            salary=120000,
        )
        create_vacancy(role="Frontend", salary=50000)

        response = self.client.get(
            "/vacancies/",
            {
                "project_id": str(project.id),
                "role_contains": "Python",
                "salary_min": "100000",
                "salary_max": "150000",
                "required_experience": "no_experience",
                "work_schedule": "full_time",
                "work_format": "remote",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data["results"]], [target.id])

    def test_list_excludes_vacancies_older_than_90_days(self):
        create_vacancy(
            role="Old vacancy",
            datetime_created=timezone.now() - timedelta(days=91),
        )
        fresh = create_vacancy(role="Fresh vacancy")

        response = self.client.get("/vacancies/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data["results"]], [fresh.id])

    def test_detail_returns_vacancy_with_project_info(self):
        vacancy = create_vacancy(role="Detail vacancy")

        response = self.client.get(f"/vacancies/{vacancy.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], vacancy.id)
        self.assertEqual(response.data["role"], "Detail vacancy")
        self.assertEqual(response.data["project"]["id"], vacancy.project.id)

    def test_project_leader_can_close_vacancy_and_decline_pending_responses(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(project=project, is_active=True)
        response_to_decline = create_vacancy_response(vacancy=vacancy)
        self.client.force_authenticate(leader)

        response = self.client.put(
            f"/vacancies/{vacancy.id}/",
            {
                "role": vacancy.role,
                "description": vacancy.description,
                "is_active": False,
                "required_experience": "без опыта",
                "work_schedule": "полный рабочий день",
                "work_format": "удаленная работа",
                "salary": vacancy.salary,
            },
            format="json",
        )

        response_to_decline.refresh_from_db()
        vacancy.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(vacancy.is_active)
        self.assertIsNotNone(vacancy.datetime_closed)
        self.assertFalse(response_to_decline.is_approved)

    def test_non_leader_cannot_update_vacancy(self):
        vacancy = create_vacancy()
        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)

        response = self.client.patch(
            f"/vacancies/{vacancy.id}/",
            {"role": "Changed"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
