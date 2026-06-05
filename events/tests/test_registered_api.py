from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from events.tests.helpers import build_event, build_user


class UserRegisteredEventsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_current_user_events_returns_only_registered_events(self):
        user = build_user(prefix="current")
        outsider = build_user(prefix="outsider")
        registered_event = build_event(title="Моё мероприятие")
        build_event(title="Чужое мероприятие")
        registered_event.registered_users.add(user)

        self.client.force_authenticate(user)
        response = self.client.get("/auth/users/current/events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [registered_event.id])

        self.client.force_authenticate(outsider)
        outsider_response = self.client.get("/auth/users/current/events/")

        self.assertEqual(outsider_response.status_code, status.HTTP_200_OK)
        self.assertEqual(outsider_response.data, [])
