from django.db import IntegrityError, transaction
from django.test import TestCase

from news.tests.helpers import create_user
from notifications.models import Notification
from notifications.services import create_notification, create_notifications


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.recipient = create_user(prefix="service-recipient")
        self.actor = create_user(prefix="service-actor")

    def create(self, **overrides):
        params = {
            "recipient_id": self.recipient.pk,
            "actor_id": self.actor.pk,
            "notification_type": Notification.Type.PROJECT_INVITE_CREATED,
            "title": "Приглашение",
            "message": "Вас пригласили в проект.",
            "action_url": "/office/projects/invites",
            "event_key": "project-invite:1:created",
        }
        params.update(overrides)
        return create_notification(**params)

    def test_duplicate_event_is_idempotent(self):
        first = self.create()
        second = self.create(title="Повтор не должен изменить снимок")

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(second.title, "Приглашение")

    def test_self_notification_is_skipped(self):
        result = self.create(actor_id=self.recipient.pk)

        self.assertIsNone(result)
        self.assertFalse(Notification.objects.exists())

    def test_bulk_service_deduplicates_recipients_and_skips_actor(self):
        second = create_user(prefix="service-second")

        created = create_notifications(
            recipient_ids=[
                self.recipient.pk,
                self.recipient.pk,
                self.actor.pk,
                second.pk,
            ],
            actor_id=self.actor.pk,
            notification_type=Notification.Type.APPLICATION_SUBMITTED,
            title="Заявка",
            message="Отправлена новая заявка.",
            action_url="/office/program/1",
            event_key="application:1:submitted",
        )

        self.assertEqual(len(created), 2)
        self.assertEqual(
            set(Notification.objects.values_list("recipient_id", flat=True)),
            {self.recipient.pk, second.pk},
        )

    def test_only_internal_office_urls_are_allowed(self):
        invalid_urls = (
            "https://example.com/office/news/1",
            "//example.com/office/news/1",
            "/projects/1",
            "/office/news/1#fragment",
            "/office/..\\admin",
        )

        for index, action_url in enumerate(invalid_urls):
            with self.subTest(action_url=action_url), self.assertRaises(ValueError):
                self.create(action_url=action_url, event_key="invalid:" + str(index))

        self.assertFalse(Notification.objects.exists())

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.create(notification_type="unknown")

    def test_notification_rolls_back_with_business_transaction(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.create()
                raise RuntimeError("rollback")

        self.assertFalse(Notification.objects.exists())

    def test_database_constraint_guards_duplicate_recipient_event(self):
        self.create()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Notification.objects.create(
                    recipient=self.recipient,
                    type=Notification.Type.NEWS_COMMENT_CREATED,
                    category=Notification.Category.NEWS,
                    title="Дубликат",
                    message="Дубликат",
                    event_key="project-invite:1:created",
                )

    def test_every_declared_type_has_category_and_can_be_created(self):
        for index, (notification_type, _label) in enumerate(Notification.Type.choices):
            self.create(
                notification_type=notification_type,
                event_key="type:" + str(index),
            )

        self.assertEqual(Notification.objects.count(), len(Notification.Type.choices))
        self.assertFalse(Notification.objects.filter(category="").exists())

    def test_actor_deletion_keeps_notification_and_recipient_deletion_cascades(self):
        notification = self.create()
        self.actor.delete()

        notification.refresh_from_db()
        self.assertIsNone(notification.actor_id)

        self.recipient.delete()
        self.assertFalse(Notification.objects.exists())
