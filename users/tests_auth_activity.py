from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from users.authentication import get_last_activity_cache_key
from users.models import CustomUser


class JwtActivityTrackingTests(APITestCase):
    def setUp(self):
        self.email = "activity_test@example.com"
        self.password = "very_strong_password"
        self.user = CustomUser.objects.create_user(
            email=self.email,
            password=self.password,
            first_name="Иван",
            last_name="Иванов",
            birthday="2000-01-01",
            is_active=True,
        )

    def _obtain_access_token(self) -> str:
        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.email, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        return response.data["access"]

    def test_token_obtain_pair_updates_last_login(self):
        old_login = timezone.now() - timedelta(days=1)
        CustomUser.objects.filter(id=self.user.id).update(last_login=old_login)

        response = self.client.post(
            reverse("token_obtain_pair"),
            {"email": self.email, "password": self.password},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)
        self.assertGreater(self.user.last_login, old_login)

    def test_last_activity_updates_with_throttle(self):
        cache.delete(get_last_activity_cache_key(self.user.id))
        CustomUser.objects.filter(id=self.user.id).update(last_activity=None)

        access = self._obtain_access_token()
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        first_response = api_client.get("/auth/specialists/")
        self.assertEqual(first_response.status_code, 200)
        self.user.refresh_from_db()
        first_activity = self.user.last_activity
        self.assertIsNotNone(first_activity)

        second_response = api_client.get("/auth/specialists/")
        self.assertEqual(second_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_activity, first_activity)

        # Simulate throttle window end for deterministic testing.
        old_activity = first_activity - timedelta(hours=1)
        CustomUser.objects.filter(id=self.user.id).update(last_activity=old_activity)
        cache.delete(get_last_activity_cache_key(self.user.id))

        third_response = api_client.get("/auth/specialists/")
        self.assertEqual(third_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertGreater(self.user.last_activity, old_activity)

    @patch("users.authentication.cache.add", side_effect=Exception("cache is down"))
    def test_last_activity_cache_failure_does_not_break_auth(self, _cache_add_mock):
        CustomUser.objects.filter(id=self.user.id).update(last_activity=None)
        access = self._obtain_access_token()

        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = api_client.get("/auth/specialists/")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_activity)

    @patch("users.authentication.get_user_model")
    def test_last_activity_db_failure_does_not_break_auth(self, get_user_model_mock):
        fake_qs = MagicMock()
        fake_qs.update.side_effect = Exception("db is down")
        fake_model = MagicMock()
        fake_model.objects.filter.return_value = fake_qs
        get_user_model_mock.return_value = fake_model

        access = self._obtain_access_token()
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = api_client.get("/auth/specialists/")
        self.assertEqual(response.status_code, 200)
        fake_model.objects.filter.assert_called_once_with(id=self.user.id)
        fake_qs.update.assert_called_once()
