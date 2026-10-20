from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core import mail
from django.db import connections, transaction
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from rest_framework.test import APIClient

from partner_programs.models import (
    ProgramRegistration,
    RegistrationConnectionRequest,
    RegistrationConnectionNotification,
)
from partner_programs.services.registration_notifications import (
    deliver_notification,
    dispatch_pending_notifications,
)
from partner_programs.tests.helpers import create_partner_program, create_user
from project_rates.models import ExpertInvitation, ExpertJoinedNotification
from django.utils import timezone
from datetime import timedelta


SETTINGS = {
    "EXPERT_WORKSPACE_FRONTEND_URL": "https://dev.procollab.ru",
    "EMAIL_USER": "no-reply@example.test",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "CELERY_TASK_ALWAYS_EAGER": True,
    "CELERY_TASK_EAGER_PROPAGATES": True,
    "CELERY_BROKER_URL": "memory://",
    "CELERY_RESULT_BACKEND": "cache+memory://",
    "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
}


@override_settings(**SETTINGS)
class RegistrationRequestNotificationTests(TestCase):
    def setUp(self):
        self.program = create_partner_program(name="Тестовый чемпионат")
        self.manager = create_user(is_active=True, first_name="Анна", last_name="Иванова")
        self.admin = create_user(is_active=True, is_staff=True)
        self.superuser = create_user(is_active=True, is_superuser=True)
        self.program.managers.add(self.manager)
        self.config = ProgramRegistration.objects.create(program=self.program)
        self.url = f"/programs/{self.program.pk}/management/registration/connection/"
        self.inbox = "/core/notifications/"
        self.client = APIClient()
        self.payload = {
            "url": "https://event.example.test",
            "comment": "Нужна интеграция",
            "contact": "@organizer",
        }

    def submit(self, data=None, execute=True):
        self.client.force_authenticate(self.manager)
        with self.captureOnCommitCallbacks(execute=execute):
            response = self.client.post(self.url, data or self.payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_request_notifies_all_active_system_administrators_after_commit(self):
        create_user(is_active=False, is_staff=True)
        create_user(is_active=True, user_type=0)
        self.client.force_authenticate(self.manager)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.post(self.url, self.payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(RegistrationConnectionRequest.objects.count(), 1)
        self.assertEqual(RegistrationConnectionNotification.objects.count(), 2)
        callbacks[0]()
        self.assertEqual(
            {message.to[0] for message in mail.outbox},
            {self.admin.email, self.superuser.email},
        )
        body = mail.outbox[0].body
        for text in (
            self.program.name,
            self.payload["url"],
            "Анна Иванова",
            self.manager.email,
            "Нужна интеграция",
            "@organizer",
            f"https://dev.procollab.ru/admin/partner_programs/programregistration/{self.config.pk}/change/",
        ):
            self.assertIn(text, body)
        self.config.refresh_from_db()
        self.assertEqual(self.config.external_status, "requested")
        self.assertEqual(self.config.external_url, "")

    def test_duplicate_request_and_task_do_not_send_again_but_changes_create_new_snapshot(
        self,
    ):
        self.submit()
        self.config.refresh_from_db()
        revision, requested_at = self.config.revision, self.config.requested_at
        self.submit()
        for notice in RegistrationConnectionNotification.objects.all():
            deliver_notification(notice.pk)
        self.config.refresh_from_db()
        self.assertEqual(
            (self.config.revision, self.config.requested_at), (revision, requested_at)
        )
        self.assertEqual(len(mail.outbox), 2)
        self.submit({**self.payload, "comment": "Другой комментарий"})
        self.assertEqual(len(mail.outbox), 4)
        self.assertEqual(
            list(
                RegistrationConnectionRequest.objects.order_by("pk").values_list(
                    "comment", flat=True
                )
            ),
            ["Нужна интеграция", "Другой комментарий"],
        )

    def test_invalid_foreign_and_connected_requests_do_not_emit(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.client.post(self.url, {"url": "invalid"}, format="json").status_code, 400
        )
        self.client.force_authenticate(create_user(is_active=True))
        self.assertEqual(
            self.client.post(self.url, self.payload, format="json").status_code, 403
        )
        self.config.external_status = "connected"
        self.config.external_url = "https://form.example.test"
        self.config.save()
        self.submit()
        self.assertFalse(RegistrationConnectionRequest.objects.exists())
        self.assertFalse(RegistrationConnectionNotification.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_rollback_does_not_leave_event_or_dispatch_mail(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.submit(execute=False)
                    raise ValueError("rollback")
            except ValueError:
                pass
        self.assertFalse(RegistrationConnectionRequest.objects.exists())
        self.assertFalse(RegistrationConnectionNotification.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_private_inbox_read_and_role_revocation(self):
        self.submit()
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.inbox)
        self.assertEqual(response.data["unread_count"], 1)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        notice = response.data["results"][0]
        self.assertEqual(notice["kind"], "registration_connection")
        self.assertEqual(notice["registration_id"], self.config.pk)
        self.assertEqual(notice["program_id"], self.program.pk)
        path = f"{self.inbox}{notice['id']}/read/"
        read = self.client.post(path, {}).data
        self.assertEqual(read["unread_count"], 0)
        self.assertEqual(self.client.post(path, {}).data, read)
        for other in (self.superuser, self.manager):
            self.client.force_authenticate(other)
            self.assertEqual(self.client.post(path, {}).status_code, 404)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get(self.inbox).data["results"], [])
        self.admin.is_staff = False
        self.admin.save(update_fields=["is_staff"])
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.inbox).data["results"], [])
        self.assertEqual(self.client.post(path, {}).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.inbox).status_code, 401)
        self.assertEqual(self.client.post(path, {}).status_code, 401)

    def test_unified_inbox_retains_expert_notices_and_legacy_api(self):
        self.submit()
        self.program.managers.add(self.admin)
        invitation = ExpertInvitation.objects.create(
            partner_program=self.program,
            email="expert@example.test",
            token_digest="f" * 64,
            expires_at=timezone.now() + timedelta(days=1),
        )
        old = ExpertJoinedNotification.objects.create(
            invitation=invitation,
            recipient=self.admin,
            expert_name="Эксперт",
            expert_email="expert@example.test",
        )
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.inbox).data
        self.assertEqual(response["unread_count"], 2)
        self.assertEqual(
            {row["kind"] for row in response["results"]},
            {"expert_joined", "registration_connection"},
        )
        self.assertEqual(len({row["id"] for row in response["results"]}), 2)
        self.assertEqual(
            self.client.post(f"{self.inbox}expert_joined:{old.pk}/read/", {}).data[
                "unread_count"
            ],
            1,
        )
        legacy = self.client.get("/evaluation/notifications/").data
        self.assertEqual(len(legacy["results"]), 1)
        self.assertEqual(legacy["results"][0]["id"], old.pk)
        self.assertEqual(legacy["unread_count"], 0)

    def test_bad_notification_keys_are_not_found(self):
        self.client.force_authenticate(self.admin)
        for key in (
            "other:1",
            "expert_joined:0",
            "registration_connection:-1",
            "expert_joined:" + "9" * 20,
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    self.client.post(f"{self.inbox}{key}/read/", {}).status_code, 404
                )

    def test_broker_failure_preserves_in_app_notice_and_recovers(self):
        with patch(
            "partner_programs.tasks.send_registration_connection_notification.delay",
            side_effect=RuntimeError("broker down"),
        ):
            self.submit()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            RegistrationConnectionNotification.objects.filter(
                delivery_status="queued"
            ).count(),
            2,
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.inbox).data["unread_count"], 1)
        dispatch_pending_notifications()
        self.assertEqual(len(mail.outbox), 2)
        dispatch_pending_notifications()
        self.assertEqual(len(mail.outbox), 2)

    def test_smtp_failure_attempts_are_persisted_and_bounded(self):
        self.submit(execute=False)
        notice = RegistrationConnectionNotification.objects.get(recipient=self.admin)
        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=RuntimeError("SMTP down"),
        ):
            for attempt in range(1, 5):
                with self.assertRaises(RuntimeError):
                    deliver_notification(notice.pk)
                notice.refresh_from_db()
                self.assertEqual(notice.attempts, attempt)
        self.assertEqual(notice.delivery_status, "failed")
        deliver_notification(notice.pk)
        self.assertEqual(len(mail.outbox), 0)

    def test_transient_delivery_failure_recovers_without_resending_sent_notifications(
        self,
    ):
        self.submit(execute=False)
        notice = RegistrationConnectionNotification.objects.get(recipient=self.admin)
        with patch("django.core.mail.EmailMultiAlternatives.send", return_value=0):
            with self.assertRaises(RuntimeError):
                deliver_notification(notice.pk)
        dispatch_pending_notifications()
        self.assertEqual(len(mail.outbox), 2)
        notice.refresh_from_db()
        self.assertEqual(notice.attempts, 2)
        self.assertEqual(notice.delivery_status, "sent")

    def test_pending_delivery_stops_after_administrator_rights_are_removed(self):
        self.submit(execute=False)
        notice = RegistrationConnectionNotification.objects.get(recipient=self.admin)
        self.admin.is_staff = False
        self.admin.save(update_fields=["is_staff"])
        deliver_notification(notice.pk)
        notice.refresh_from_db()
        self.assertEqual(notice.delivery_status, "cancelled")
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_administrators_are_recovered_without_backfilling_legacy_requests(
        self,
    ):
        for user in (self.admin, self.superuser):
            user.is_active = False
            user.save(update_fields=["is_active"])
        self.submit()
        self.assertEqual(RegistrationConnectionRequest.objects.count(), 1)
        self.assertFalse(RegistrationConnectionNotification.objects.exists())
        ProgramRegistration.objects.create(
            program=create_partner_program(), external_status="requested"
        )
        self.admin.is_active = True
        self.admin.save(update_fields=["is_active"])
        dispatch_pending_notifications()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(RegistrationConnectionRequest.objects.count(), 1)

    def test_optional_details_html_escaping_and_user_names_are_preserved(self):
        self.submit(
            {
                "url": "https://event.example.test",
                "comment": "<script>alert(1)</script>",
                "contact": "",
            }
        )
        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Не указан", html)
        self.assertNotIn(chr(0x451), html)


@override_settings(**SETTINGS)
class RegistrationNotificationConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_identical_requests_create_one_event_and_delivery(self):
        manager = create_user(is_active=True)
        create_user(is_active=True, is_staff=True)
        program = create_partner_program()
        program.managers.add(manager)
        config = ProgramRegistration.objects.create(program=program)
        barrier = Barrier(2)

        def worker():
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(manager)
                barrier.wait(timeout=10)
                return client.post(
                    f"/programs/{program.pk}/management/registration/connection/",
                    {"url": "https://event.example.test"},
                    format="json",
                ).status_code
            finally:
                connections.close_all()

        with patch(
            "partner_programs.tasks.send_registration_connection_notification.delay"
        ) as queue:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker) for _ in range(2)]
                self.assertEqual(
                    [future.result(timeout=20) for future in futures], [200, 200]
                )
            self.assertEqual(queue.call_count, 1)
        self.assertEqual(RegistrationConnectionRequest.objects.count(), 1)
        self.assertEqual(RegistrationConnectionNotification.objects.count(), 1)
        config.refresh_from_db()
        self.assertEqual(config.revision, 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_workers_send_only_one_email(self):
        manager = create_user(is_active=True)
        admin = create_user(is_active=True, is_staff=True)
        config = ProgramRegistration.objects.create(program=create_partner_program())
        event = RegistrationConnectionRequest.objects.create(
            registration=config,
            revision=1,
            requested_by=manager,
            requester_name="Организатор",
            requester_email=manager.email,
            website_url="https://event.example.test",
        )
        notice = RegistrationConnectionNotification.objects.create(
            request=event, recipient=admin
        )
        barrier = Barrier(2)

        def worker():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                deliver_notification(notice.pk)
            finally:
                connections.close_all()

        with patch(
            "django.core.mail.EmailMultiAlternatives.send", return_value=1
        ) as send:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker) for _ in range(2)]
                for future in futures:
                    future.result(timeout=20)
            self.assertEqual(send.call_count, 1)
        notice.refresh_from_db()
        self.assertEqual(notice.attempts, 1)
        self.assertEqual(notice.delivery_status, "sent")
