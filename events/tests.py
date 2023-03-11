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

        self.title = "TITLE"
        self.text = "TEXT"
        self.short_text = "njknk"
        self.cover_url = "https://example.com/"
        self.datetime_of_event = "2023-03-11T14:31:22+03:00"

        self.CREATE_DATA = {
            "title": self.title,
            "text": self.text,
            "short_text": self.short_text,
            "cover_url": self.cover_url,
            "datetime_of_event": self.datetime_of_event,
        }

    def test_events_creation(self):
        user = self._user_create(is_staff=True)
        request = self.factory.post("events/", self.CREATE_DATA, format='json')
        force_authenticate(request, user=user)
        response = self.event_list_view(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["title"], self.title)
        self.assertEqual(response.data["short_text"], self.short_text)
        self.assertEqual(response.data["cover_url"], self.cover_url)
        self.assertEqual(response.data["datetime_of_event"], self.datetime_of_event)

    def test_events_creation_by_not_staff_user(self):
        user = self._user_create(is_staff=False)
        request = self.factory.post("events/", self.CREATE_DATA)
        force_authenticate(request, user=user)
        response = self.event_list_view(request)
        self.assertEqual(response.status_code, 403)

    def test_events_update(self):
        user = self._user_create(is_staff=True)
        request = self.factory.post("events/", self.CREATE_DATA)
        force_authenticate(request, user=user)
        response = self.event_list_view(request)

        event_id = response.data["id"]
        news = Event.objects.get(id=event_id)

        request = self.factory.patch(f"event/{news.pk}/", {"text": "New text"})
        force_authenticate(request, user=user)
        response = self.event_detail_view(request, pk=news.pk)

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
