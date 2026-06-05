from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from events.tests.helpers import build_event


class EventsPublicURLTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_events_public_urls_are_not_mounted(self):
        event = build_event()

        urls = [
            "/events/",
            f"/events/{event.id}/",
            f"/events/{event.id}/registered/",
            "/events/types/",
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
