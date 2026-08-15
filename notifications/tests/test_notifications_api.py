from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from news.tests.helpers import create_user
from notifications.models import Notification


def create_notification(*, recipient, actor=None, suffix="1", read=False):
    return Notification.objects.create(
        recipient=recipient,
        actor=actor,
        type=Notification.Type.PROJECT_INVITE_CREATED,
        category=Notification.Category.PROJECT,
        title=f"Уведомление {suffix}",
        message="Безопасное сообщение",
        action_url="/office/projects/invites",
        event_key="test:" + suffix,
        read_at=timezone.now() if read else None,
    )


class NotificationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="notification-recipient")
        self.actor = create_user(prefix="notification-actor")
        self.other = create_user(prefix="notification-other")

    def test_all_endpoints_require_authentication(self):
        notification = create_notification(recipient=self.user)

        responses = (
            self.client.get("/notifications/"),
            self.client.get("/notifications/unread-count/"),
            self.client.post(f"/notifications/{notification.pk}/read/"),
            self.client.post("/notifications/read-all/"),
        )

        self.assertTrue(all(response.status_code == 401 for response in responses))

    def test_list_is_paginated_newest_first_and_scoped_to_recipient(self):
        first = create_notification(recipient=self.user, actor=self.actor, suffix="1")
        second = create_notification(recipient=self.user, actor=self.actor, suffix="2")
        create_notification(recipient=self.other, suffix="other")
        self.client.force_authenticate(self.user)

        response = self.client.get("/notifications/?limit=1&offset=0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["unread_count"], 2)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.assertEqual(response.data["results"][0]["id"], second.pk)
        self.assertNotEqual(response.data["results"][0]["id"], first.pk)

        next_response = self.client.get("/notifications/?limit=1&offset=1")
        self.assertEqual(next_response.data["results"][0]["id"], first.pk)
        self.assertIsNone(next_response.data["next"])
        self.assertIsNotNone(next_response.data["previous"])

    def test_unread_filter_and_count_use_all_user_notifications(self):
        unread = create_notification(recipient=self.user, suffix="unread")
        create_notification(recipient=self.user, suffix="read", read=True)
        self.client.force_authenticate(self.user)

        response = self.client.get("/notifications/?unread=true")
        count_response = self.client.get("/notifications/unread-count/")

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["unread_count"], 1)
        self.assertEqual(response.data["results"][0]["id"], unread.pk)
        self.assertEqual(count_response.data, {"unread_count": 1})

    def test_read_is_idempotent_and_preserves_first_timestamp(self):
        notification = create_notification(recipient=self.user)
        self.client.force_authenticate(self.user)

        first = self.client.post(f"/notifications/{notification.pk}/read/")
        first_read_at = first.data["read_at"]
        second = self.client.post(f"/notifications/{notification.pk}/read/")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["read_at"], first_read_at)

    def test_foreign_notification_is_hidden_by_404(self):
        notification = create_notification(recipient=self.other)
        self.client.force_authenticate(self.user)

        response = self.client.post(f"/notifications/{notification.pk}/read/")

        self.assertEqual(response.status_code, 404)
        notification.refresh_from_db()
        self.assertIsNone(notification.read_at)

    def test_read_all_changes_only_current_users_unread_notifications(self):
        own_unread = create_notification(recipient=self.user, suffix="own-unread")
        own_read = create_notification(recipient=self.user, suffix="own-read", read=True)
        other_unread = create_notification(recipient=self.other, suffix="other-unread")
        self.client.force_authenticate(self.user)

        response = self.client.post("/notifications/read-all/")

        self.assertEqual(response.data, {"updated": 1, "unread_count": 0})
        own_unread.refresh_from_db()
        own_read.refresh_from_db()
        other_unread.refresh_from_db()
        self.assertIsNotNone(own_unread.read_at)
        self.assertIsNotNone(own_read.read_at)
        self.assertIsNone(other_unread.read_at)

    def test_actor_contract_does_not_expose_private_fields(self):
        self.actor.avatar = "https://cdn.example.com/avatar.png"
        self.actor.save(update_fields=["avatar"])
        create_notification(recipient=self.user, actor=self.actor)
        self.client.force_authenticate(self.user)

        response = self.client.get("/notifications/")

        actor = response.data["results"][0]["actor"]
        self.assertEqual(
            set(actor),
            {"id", "first_name", "last_name", "avatar"},
        )
        serialized = str(response.data).lower()
        for forbidden in ("email", "phone", "birthday", "is_staff", "password"):
            self.assertNotIn(forbidden, serialized)

    def test_list_has_fixed_query_count_for_many_notifications(self):
        for index in range(12):
            create_notification(
                recipient=self.user,
                actor=self.actor,
                suffix=f"query-{index}",
            )
        self.client.force_authenticate(self.user)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/notifications/?limit=20")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 12)
        self.assertEqual(len(queries), 3)
