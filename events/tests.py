from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from tests.constants import USER_CREATE_DATA
from users.models import CustomUser
from users.views import UserList

from .models import Event
from .views import EventDetail, EventsList


class EventsTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

        self.user_list_view = UserList.as_view()

        self.event_list_view = EventsList.as_view()
        self.event_detail_view = EventDetail.as_view()

        self.TITLE = "TITLE"
        self.TEXT = "TEXT"
        self.SHORT_TEXT = "njknk"
        self.COVER_URL = "https://example.com/"
        self.DATETIME_OF_EVENT = "2023-03-11T14:31:22+03:00"

        self.CREATE_DATA = {
            "title": self.TITLE,
            "text": self.TEXT,
            "short_text": self.SHORT_TEXT,
            "cover_url": self.COVER_URL,
            "datetime_of_event": self.DATETIME_OF_EVENT,
        }

    def test_events_creation(self):
        user = self._user_create(is_staff=True)
        request = self.factory.post("events/", self.CREATE_DATA, format='json')
        force_authenticate(request, user=user)
        response = self.event_list_view(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["title"], self.TITLE)
        self.assertEqual(response.data["short_text"], self.SHORT_TEXT)
        self.assertEqual(response.data["cover_url"], self.COVER_URL)
        self.assertEqual(response.data["datetime_of_event"], self.DATETIME_OF_EVENT)

    def test_events_creation_by_not_staff_user(self):
        user = self._user_create(is_staff=False)
        request = self.factory.post("events/", self.CREATE_DATA)
        force_authenticate(request, user=user)
        response = self.event_list_view(request)
        self.assertEqual(response.status_code, 403)

    def test_event_creation_with_empty_text(self):
        user = self._user_create(is_staff=True)
        new_data = self.CREATE_DATA
        del new_data["text"]

        request = self.factory.post("events/", new_data)
        force_authenticate(request, user=user)
        response = self.event_list_view(request)
        event_id = response.data["id"]
        event = Event.objects.get(pk=event_id)
        request = self.factory.get(f"event/{event.pk}/")
        response = self.event_detail_view(request, pk=event.pk)
        print(response.data)
        self.assertEqual(response.status_code, 400)

    def test_events_update(self):
        user = self._user_create(is_staff=True)
        request = self.factory.post("events/", self.CREATE_DATA)
        force_authenticate(request, user=user)
        response = self.event_list_view(request)

        event_id = response.data["id"]
        event = Event.objects.get(id=event_id)

        request = self.factory.patch(f"event/{event.pk}/", {"text": "New text"})
        force_authenticate(request, user=user)
        response = self.event_detail_view(request, pk=event.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["text"], "New text")

    def test_event_creation_with_empty_data(self):
        user = self._user_create(is_staff=True)
        request = self.factory.post("events/", {})

        force_authenticate(request, user=user)
        response = self.event_list_view(request)
        self.assertEqual(response.status_code, 400)

    def _user_create(self, is_staff=False):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_staff = is_staff
        user.is_active = True
        user.save()
        return user
