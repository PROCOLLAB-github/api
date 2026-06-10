from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from core.utils import get_users_online_cache_key
from metrics.tests.helpers import create_project, create_user, create_vacancy


class MetricsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def test_anonymous_user_cannot_access_metrics(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 401)

    def test_staff_user_can_get_metrics_payload(self):
        staff = create_user(prefix="metrics-staff", is_staff=True)
        user = create_user(prefix="metrics-regular")
        project = create_project(leader=user)
        create_vacancy(project=project)
        cache.set(get_users_online_cache_key(), {staff.id, user.id})
        self.client.force_authenticate(staff)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_CustomUser_count"], 2)
        self.assertEqual(response.data["total_Project_count"], 1)
        self.assertEqual(response.data["total_Vacancy_count"], 1)
        self.assertEqual(response.data["current_online_users"], 2)

    def test_non_staff_user_cannot_access_metrics(self):
        user = create_user(prefix="metrics-regular")
        self.client.force_authenticate(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 403)
