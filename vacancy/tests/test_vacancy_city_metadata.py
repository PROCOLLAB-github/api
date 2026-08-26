from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from vacancy.constants import WorkFormat
from vacancy.models import Vacancy
from vacancy.serializers import ProjectVacancyListSerializer, VacancyCatalogSerializer
from vacancy.tests.helpers import create_project, create_user, vacancy_payload


class VacancyCityMetadataTests(TestCase):
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
        return response, project, leader

    def test_remote_vacancy_clears_city(self):
        response, _, _ = self.create_vacancy_as_leader(city="Москва")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["city"])
        self.assertIsNone(Vacancy.objects.get(pk=response.data["id"]).city)

    def test_office_vacancy_requires_city(self):
        response, _, _ = self.create_vacancy_as_leader(
            work_format=WorkFormat.OFFICE.value,
            city="   ",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["city"],
            ["Для офисного или смешанного формата укажите город."],
        )

    def test_office_vacancy_trims_and_returns_city(self):
        response, _, _ = self.create_vacancy_as_leader(
            work_format=WorkFormat.OFFICE.value,
            city="  Москва  ",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["city"], "Москва")
        self.assertEqual(Vacancy.objects.get(pk=response.data["id"]).city, "Москва")

    def test_hybrid_vacancy_requires_city(self):
        response, _, _ = self.create_vacancy_as_leader(
            work_format=WorkFormat.HYBRID.value,
            city=None,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("city", response.data)

    def test_legacy_hybrid_is_normalized(self):
        response, _, _ = self.create_vacancy_as_leader(
            work_format="смешанная",
            city="Казань",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["work_format"], WorkFormat.HYBRID.value)
        self.assertEqual(response.data["city"], "Казань")

    def test_patch_validates_final_office_state(self):
        response, _, leader = self.create_vacancy_as_leader()
        vacancy_id = response.data["id"]
        self.client.force_authenticate(leader)

        patch_response = self.client.patch(
            f"/vacancies/{vacancy_id}/",
            {"work_format": WorkFormat.OFFICE.value},
            format="json",
        )

        self.assertEqual(patch_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("city", patch_response.data)

    def test_switch_to_remote_clears_existing_city(self):
        response, _, leader = self.create_vacancy_as_leader(
            work_format=WorkFormat.OFFICE.value,
            city="Томск",
        )
        vacancy_id = response.data["id"]
        self.client.force_authenticate(leader)

        patch_response = self.client.patch(
            f"/vacancies/{vacancy_id}/",
            {"work_format": WorkFormat.REMOTE.value},
            format="json",
        )

        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(patch_response.data["city"])
        self.assertIsNone(Vacancy.objects.get(pk=vacancy_id).city)

    def test_project_and_catalog_serializers_expose_city_metadata(self):
        response, _, _ = self.create_vacancy_as_leader(
            work_format=WorkFormat.HYBRID.value,
            city="Самара",
        )
        vacancy = Vacancy.objects.get(pk=response.data["id"])

        project_data = ProjectVacancyListSerializer(vacancy).data
        catalog_data = VacancyCatalogSerializer(vacancy).data

        for data in (project_data, catalog_data):
            self.assertEqual(data["city"], "Самара")
            self.assertEqual(data["work_format"], WorkFormat.HYBRID.value)
            self.assertIn("required_experience", data)
            self.assertIn("work_schedule", data)
            self.assertIn("salary", data)
