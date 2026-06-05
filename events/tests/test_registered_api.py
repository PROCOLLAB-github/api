from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from events.tests.helpers import build_event, build_user


class EventRegisteredUsersAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_registered_users_endpoint_returns_event_users(self):
        event = build_event()
        registered_user = build_user(prefix="registered")
        outsider = build_user(prefix="outsider")
        event.registered_users.add(registered_user)

        response = self.client.get(f"/events/{event.id}/registered/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [registered_user.id])
        self.assertNotIn(outsider.id, [item["id"] for item in response.data])

    def test_registered_users_endpoint_returns_404_for_missing_event(self):
        response = self.client.get("/events/999999/registered/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_current_user_events_returns_only_registered_events(self):
        user = build_user(prefix="current")
        registered_event = build_event(title="Моё мероприятие")
        build_event(title="Чужое мероприятие")
        registered_event.registered_users.add(user)
        self.client.force_authenticate(user)

        response = self.client.get("/auth/users/current/events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [registered_event.id])
