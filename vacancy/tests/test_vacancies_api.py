from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from vacancy.constants import WorkExperience, WorkFormat, WorkSchedule
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

    def create_vacancy_as_leader(self, **overrides):
        leader = create_user(prefix="city-leader")
        project = create_project(leader=leader)
        self.client.force_authenticate(leader)
        response = self.client.post(
            "/vacancies/",
            vacancy_payload(project, **overrides),
            format="json",
        )
        return response, project

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

    def test_create_remote_vacancy_without_city(self):
        response, _ = self.create_vacancy_as_leader()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["city"])
        self.assertIsNone(Vacancy.objects.get(pk=response.data["id"]).city)

    def test_create_remote_vacancy_clears_city(self):
        response, _ = self.create_vacancy_as_leader(city="Москва")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["city"])
        self.assertIsNone(Vacancy.objects.get(pk=response.data["id"]).city)

    def test_create_office_vacancy_requires_city(self):
        response, _ = self.create_vacancy_as_leader(
            work_format=WorkFormat.OFFICE.value,
            city=None,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["city"],
            ["Для офисного или смешанного формата укажите город."],
        )

    def test_create_office_vacancy_trims_city(self):
        response, _ = self.create_vacancy_as_leader(
            work_format=WorkFormat.OFFICE.value,
            city="  Москва  ",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["city"], "Москва")
        self.assertEqual(Vacancy.objects.get(pk=response.data["id"]).city, "Москва")

    def test_create_hybrid_vacancy_requires_city(self):
        response, _ = self.create_vacancy_as_leader(
            work_format=WorkFormat.HYBRID.value,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("city", response.data)

    def test_create_hybrid_vacancy_returns_city(self):
        response, _ = self.create_vacancy_as_leader(
            work_format=WorkFormat.HYBRID.value,
            city="Казань",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["work_format"], WorkFormat.HYBRID.value)
        self.assertEqual(response.data["city"], "Казань")

    def test_create_accepts_legacy_hybrid_work_format(self):
        response, _ = self.create_vacancy_as_leader(
            work_format="смешанная",
            city="Томск",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        vacancy = Vacancy.objects.get(pk=response.data["id"])
        self.assertEqual(vacancy.work_format, WorkFormat.HYBRID.name.lower())
        self.assertEqual(response.data["work_format"], WorkFormat.HYBRID.value)

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

    def test_public_list_cannot_include_inactive_vacancies_by_filter(self):
        create_vacancy(role="Active vacancy", is_active=True)
        create_vacancy(role="Inactive vacancy", is_active=False)

        response = self.client.get("/vacancies/", {"is_active": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [],
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

    def test_list_includes_active_vacancies_older_than_90_days(self):
        old = create_vacancy(
            role="Old vacancy",
            datetime_created=timezone.now() - timedelta(days=91),
        )
        fresh = create_vacancy(role="Fresh vacancy")

        response = self.client.get("/vacancies/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [fresh.id, old.id],
        )

    def test_detail_returns_vacancy_with_project_info(self):
        vacancy = create_vacancy(role="Detail vacancy", city=None)

        response = self.client.get(f"/vacancies/{vacancy.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], vacancy.id)
        self.assertEqual(response.data["role"], "Detail vacancy")
        self.assertEqual(response.data["project"]["id"], vacancy.project.id)
        self.assertIsNone(response.data["city"])

    def test_patch_validates_city_against_final_work_format(self):
        leader = create_user(prefix="patch-city-leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(
            project=project,
            work_format=WorkFormat.OFFICE.name.lower(),
            city="Москва",
        )
        self.client.force_authenticate(leader)

        response = self.client.patch(
            f"/vacancies/{vacancy.id}/",
            {"city": "\t  "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("city", response.data)
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.city, "Москва")

    def test_patch_rejects_switch_to_hybrid_without_city(self):
        leader = create_user(prefix="patch-hybrid-leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(project=project, city=None)
        self.client.force_authenticate(leader)

        response = self.client.patch(
            f"/vacancies/{vacancy.id}/",
            {"work_format": WorkFormat.HYBRID.value},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("city", response.data)
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.work_format, WorkFormat.REMOTE.name.lower())

    def test_patch_hybrid_uses_existing_city_and_can_update_it(self):
        leader = create_user(prefix="patch-existing-city-leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(
            project=project,
            work_format=WorkFormat.OFFICE.name.lower(),
            city="Москва",
        )
        self.client.force_authenticate(leader)

        switched = self.client.patch(
            f"/vacancies/{vacancy.id}/",
            {"work_format": WorkFormat.HYBRID.value},
            format="json",
        )
        updated = self.client.patch(
            f"/vacancies/{vacancy.id}/",
            {"city": "  Казань  "},
            format="json",
        )

        self.assertEqual(switched.status_code, status.HTTP_200_OK)
        self.assertEqual(switched.data["city"], "Москва")
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["city"], "Казань")

    def test_put_validates_final_office_city(self):
        leader = create_user(prefix="put-city-leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(
            project=project,
            work_format=WorkFormat.OFFICE.name.lower(),
            city="Москва",
        )
        self.client.force_authenticate(leader)

        response = self.client.put(
            f"/vacancies/{vacancy.id}/",
            {
                "role": vacancy.role,
                "specialization": vacancy.specialization,
                "description": vacancy.description,
                "is_active": True,
                "required_experience": WorkExperience.NO_EXPERIENCE.value,
                "work_schedule": WorkSchedule.FULL_TIME.value,
                "work_format": WorkFormat.OFFICE.value,
                "salary": vacancy.salary,
                "city": "   ",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("city", response.data)
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.city, "Москва")

    def test_patch_switch_from_office_to_remote_clears_city(self):
        leader = create_user(prefix="patch-remote-leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(
            project=project,
            work_format=WorkFormat.OFFICE.name.lower(),
            city="Москва",
        )
        self.client.force_authenticate(leader)

        response = self.client.patch(
            f"/vacancies/{vacancy.id}/",
            {"work_format": WorkFormat.REMOTE.value},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["city"])
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.work_format, WorkFormat.REMOTE.name.lower())
        self.assertIsNone(vacancy.city)

    def test_project_detail_returns_vacancy_editable_metadata(self):
        project = create_project()
        vacancy = create_vacancy(
            project=project,
            work_format=WorkFormat.HYBRID.name.lower(),
            required_experience=WorkExperience.FROM_ONE_TO_THREE_YEARS.name.lower(),
            work_schedule=WorkSchedule.FLEXIBLE_SCHEDULE.name.lower(),
            salary=150000,
            city="Санкт-Петербург",
        )

        response = self.client.get(f"/projects/{project.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        serialized = next(
            item for item in response.data["vacancies"] if item["id"] == vacancy.id
        )
        self.assertEqual(serialized["city"], "Санкт-Петербург")
        self.assertEqual(serialized["work_format"], WorkFormat.HYBRID.value)
        self.assertEqual(
            serialized["required_experience"],
            WorkExperience.FROM_ONE_TO_THREE_YEARS.value,
        )
        self.assertEqual(
            serialized["work_schedule"], WorkSchedule.FLEXIBLE_SCHEDULE.value
        )
        self.assertEqual(serialized["salary"], 150000)

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
