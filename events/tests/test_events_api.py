from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from events.models import Event
from events.tests.helpers import (
    build_event,
    build_event_payload,
    build_staff_user,
    build_user,
)


class EventReadAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_list_events_available_without_auth(self):
        event = build_event(title="Открытое мероприятие")

        response = self.client.get("/events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["id"], event.id)
        self.assertEqual(response.data[0]["title"], "Открытое мероприятие")

    def test_detail_event_available_without_auth(self):
        event = build_event(title="Детальная карточка")

        response = self.client.get(f"/events/{event.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], event.id)
        self.assertEqual(response.data["title"], "Детальная карточка")
        self.assertEqual(response.data["text"], event.text)

    def test_event_types_available_without_auth(self):
        response = self.client.get("/events/types/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            ((0, "Оффлайн"), (1, "Онлайн"), (2, "Оффлайн и онлайн")),
        )

    def test_list_events_can_be_filtered_by_title_text_and_created_date(self):
        old_event = build_event(title="Старое", text="Архивная встреча")
        Event.objects.filter(pk=old_event.pk).update(
            datetime_created=timezone.now() - timedelta(days=30)
        )
        fresh_event = build_event(title="Новый запуск", text="Demo day")

        title_response = self.client.get("/events/", {"title__contains": "Новый"})
        text_response = self.client.get("/events/", {"text__contains": "Demo"})
        date_response = self.client.get(
            "/events/",
            {"datetime_created__gt": (timezone.now() - timedelta(days=1)).isoformat()},
        )

        self.assertEqual([item["id"] for item in title_response.data], [fresh_event.id])
        self.assertEqual([item["id"] for item in text_response.data], [fresh_event.id])
        self.assertEqual([item["id"] for item in date_response.data], [fresh_event.id])


class EventMutationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_staff_user_can_create_event(self):
        user = build_staff_user()
        payload = build_event_payload(title="Создано staff-пользователем")
        self.client.force_authenticate(user)

        response = self.client.post("/events/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Создано staff-пользователем")
        self.assertTrue(Event.objects.filter(title=payload["title"]).exists())

    def test_non_staff_user_cannot_create_event(self):
        user = build_user()
        self.client.force_authenticate(user)

        response = self.client.post("/events/", build_event_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_cannot_create_event(self):
        response = self.client.post("/events/", build_event_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_staff_user_can_patch_event(self):
        user = build_staff_user()
        event = build_event(text="Старый текст")
        self.client.force_authenticate(user)

        response = self.client.patch(
            f"/events/{event.id}/",
            {"text": "Новый текст"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["text"], "Новый текст")

    def test_staff_user_can_delete_event(self):
        user = build_staff_user()
        event = build_event()
        self.client.force_authenticate(user)

        response = self.client.delete(f"/events/{event.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Event.objects.filter(pk=event.pk).exists())

    def test_create_event_rejects_empty_text(self):
        user = build_staff_user()
        self.client.force_authenticate(user)

        response = self.client.post(
            "/events/",
            build_event_payload(text=""),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_event_rejects_empty_payload(self):
        user = build_staff_user()
        self.client.force_authenticate(user)

        response = self.client.post("/events/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
