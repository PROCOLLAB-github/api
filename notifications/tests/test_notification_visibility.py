from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from news.tests.helpers import create_user
from notifications.models import Notification
from notifications.selectors import ANGULAR_NOTIFICATION_TYPES


def create_typed_notification(*, recipient, notification_type, suffix):
    return Notification.objects.create(
        recipient=recipient,
        type=notification_type,
        category=Notification.TYPE_CATEGORY[notification_type],
        title="Уведомление",
        message="Сообщение",
        action_url="/office/program/1",
        event_key=f"visibility:{suffix}",
    )


class AngularNotificationTypesTests(SimpleTestCase):
    def test_angular_surface_contains_only_production_types(self):
        self.assertEqual(
            set(ANGULAR_NOTIFICATION_TYPES),
            {
                Notification.Type.PROJECT_INVITE_CREATED,
                Notification.Type.PROJECT_INVITE_ACCEPTED,
                Notification.Type.PROJECT_INVITE_DECLINED,
                Notification.Type.PROJECT_INVITE_REVOKED,
                Notification.Type.VACANCY_RESPONSE_CREATED,
                Notification.Type.VACANCY_RESPONSE_ACCEPTED,
                Notification.Type.VACANCY_RESPONSE_DECLINED,
                Notification.Type.PROGRAM_NEWS_PUBLISHED,
                Notification.Type.PROGRAM_MATERIAL_PUBLISHED,
                Notification.Type.COURSE_ACCESS_OPENED,
            },
        )


@override_settings(NEXTGEN_SURFACE_ENABLED=False)
class NotificationVisibilityOffTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="notification-visibility-off")
        self.client.force_authenticate(self.user)
        self.visible = create_typed_notification(
            recipient=self.user,
            notification_type=Notification.Type.PROGRAM_NEWS_PUBLISHED,
            suffix="visible",
        )
        self.hidden = create_typed_notification(
            recipient=self.user,
            notification_type=Notification.Type.APPLICATION_SUBMITTED,
            suffix="hidden-application",
        )

    def test_list_and_counts_ignore_physical_nextgen_row(self):
        response = self.client.get("/notifications/")
        count_response = self.client.get("/notifications/unread-count/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["unread_count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.visible.pk)
        self.assertEqual(count_response.data, {"unread_count": 1})
        self.assertTrue(Notification.objects.filter(pk=self.hidden.pk).exists())

    def test_read_all_does_not_modify_hidden_row(self):
        response = self.client.post("/notifications/read-all/")

        self.assertEqual(response.data, {"updated": 1, "unread_count": 0})
        self.visible.refresh_from_db()
        self.hidden.refresh_from_db()
        self.assertIsNotNone(self.visible.read_at)
        self.assertIsNone(self.hidden.read_at)

    def test_hidden_notification_cannot_be_read_by_id(self):
        response = self.client.post(f"/notifications/{self.hidden.pk}/read/")

        self.assertEqual(response.status_code, 404)
        self.hidden.refresh_from_db()
        self.assertIsNone(self.hidden.read_at)


@override_settings(NEXTGEN_SURFACE_ENABLED=True)
class NotificationVisibilityOnTests(TestCase):
    def test_nextgen_row_is_visible_and_readable(self):
        client = APIClient()
        user = create_user(prefix="notification-visibility-on")
        hidden_when_off = create_typed_notification(
            recipient=user,
            notification_type=Notification.Type.APPLICATION_SUBMITTED,
            suffix="nextgen-on",
        )
        client.force_authenticate(user)

        response = client.get("/notifications/")
        read_response = client.post(f"/notifications/{hidden_when_off.pk}/read/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["unread_count"], 1)
        self.assertEqual(response.data["results"][0]["id"], hidden_when_off.pk)
        self.assertEqual(read_response.status_code, 200)
        hidden_when_off.refresh_from_db()
        self.assertIsNotNone(hidden_when_off.read_at)
