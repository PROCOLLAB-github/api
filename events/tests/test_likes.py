from django.test import TestCase

from events.models import LikesOnEvent
from events.tests.helpers import build_event, build_user


class LikesOnEventManagerTests(TestCase):
    def test_toggle_like_creates_active_like(self):
        user = build_user()
        event = build_event()

        like = LikesOnEvent.objects.toggle_like(user, event)

        self.assertEqual(like.user, user)
        self.assertEqual(like.event, event)
        self.assertTrue(like.is_liked)

    def test_toggle_like_switches_existing_like(self):
        user = build_user()
        event = build_event()
        LikesOnEvent.objects.toggle_like(user, event)

        like = LikesOnEvent.objects.toggle_like(user, event)

        self.assertFalse(like.is_liked)
        self.assertEqual(LikesOnEvent.objects.count(), 1)

    def test_get_likes_for_list_view_returns_expected_queryset(self):
        user = build_user()
        event = build_event()
        like = LikesOnEvent.objects.toggle_like(user, event)

        likes = list(LikesOnEvent.objects.get_likes_for_list_view())

        self.assertEqual(likes, [like])
