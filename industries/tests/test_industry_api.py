from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from industries.models import Industry
from industries.tests.helpers import (
    create_industry,
    create_project_with_industry,
    create_user,
)


class IndustryReadAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_anonymous_user_can_get_industry_list_ordered_by_name(self):
        beta = create_industry(name="Beta")
        alpha = create_industry(name="Alpha")

        response = self.client.get("/industries/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data],
            [alpha.id, beta.id],
        )

    def test_anonymous_user_can_get_industry_detail(self):
        industry = create_industry(name="Robotics")

        response = self.client.get(f"/industries/{industry.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], industry.id)
        self.assertEqual(response.data["name"], industry.name)
        self.assertIn("datetime_created", response.data)

    def test_missing_industry_returns_404(self):
        response = self.client.get("/industries/999999/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class IndustryWriteAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_staff_user_can_create_industry(self):
        staff = create_user(prefix="staff", is_staff=True)
        self.client.force_authenticate(staff)

        response = self.client.post(
            "/industries/",
            {"name": "Новая отрасль"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Новая отрасль")
        self.assertTrue(Industry.objects.filter(name="Новая отрасль").exists())

    def test_anonymous_user_must_authenticate_to_create_industry(self):
        response = self.client.post(
            "/industries/",
            {"name": "Закрытая отрасль"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(Industry.objects.filter(name="Закрытая отрасль").exists())

    def test_regular_user_cannot_create_industry(self):
        user = create_user(prefix="regular")
        self.client.force_authenticate(user)

        response = self.client.post(
            "/industries/",
            {"name": "Закрытая отрасль"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Industry.objects.filter(name="Закрытая отрасль").exists())

    def test_staff_user_can_update_industry(self):
        staff = create_user(prefix="staff", is_staff=True)
        industry = create_industry(name="Old")
        self.client.force_authenticate(staff)

        response = self.client.patch(
            f"/industries/{industry.id}/",
            {"name": "Updated industry"},
            format="json",
        )

        industry.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(industry.name, "Updated industry")

    def test_regular_user_cannot_update_industry(self):
        user = create_user(prefix="regular")
        industry = create_industry(name="Protected")
        self.client.force_authenticate(user)

        response = self.client.patch(
            f"/industries/{industry.id}/",
            {"name": "Unexpected"},
            format="json",
        )

        industry.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotEqual(industry.name, "Unexpected")

    def test_staff_user_can_delete_industry_and_detach_projects(self):
        staff = create_user(prefix="staff", is_staff=True)
        industry = create_industry(name="Temporary")
        project = create_project_with_industry(industry=industry)
        self.client.force_authenticate(staff)

        response = self.client.delete(f"/industries/{industry.id}/")

        project.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Industry.objects.filter(pk=industry.pk).exists())
        self.assertIsNone(project.industry)

    def test_name_is_required_on_create(self):
        staff = create_user(prefix="staff", is_staff=True)
        self.client.force_authenticate(staff)

        response = self.client.post("/industries/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

    def test_name_cannot_be_blank(self):
        staff = create_user(prefix="staff", is_staff=True)
        self.client.force_authenticate(staff)

        response = self.client.post(
            "/industries/",
            {"name": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

    def test_name_cannot_exceed_256_symbols(self):
        staff = create_user(prefix="staff", is_staff=True)
        self.client.force_authenticate(staff)

        response = self.client.post(
            "/industries/",
            {"name": "x" * 257},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)
