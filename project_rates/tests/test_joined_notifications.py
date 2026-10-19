from datetime import timedelta

from django.core import mail
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.tests.helpers import create_partner_program, create_user
from project_rates.models import ExpertInvitation, ExpertJoinedNotification
from project_rates.tasks import send_expert_joined_notification
from project_rates.workspace import accept_invitation, digest


@override_settings(
    EXPERT_WORKSPACE_FRONTEND_URL="https://dev.procollab.ru",
    EMAIL_USER="no-reply@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_BROKER_URL="memory://",
    CELERY_RESULT_BACKEND="cache+memory://",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ExpertJoinedNotificationTests(TestCase):
    def setUp(self):
        self.program = create_partner_program()
        self.managers = [create_user(is_active=True), create_user(is_active=True)]
        self.program.managers.add(*self.managers)
        self.expert = create_user(first_name="Анна", last_name="Эксперт", is_active=True)
        self.token = "test-expert-joined-invitation-0123456789"
        self.invitation = ExpertInvitation.objects.create(
            partner_program=self.program,
            email=self.expert.email.lower(),
            token_digest=digest(self.token),
            expires_at=timezone.now() + timedelta(days=1),
            invited_by=self.managers[0],
        )
        self.client = APIClient()
        self.root = "/evaluation/notifications/"

    def accept(self):
        self.client.force_authenticate(self.expert)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/evaluation/invitations/{self.token}/accept/", {}, format="json"
            )
        self.assertEqual(response.status_code, 200)

    def test_accept_notifies_each_active_organizer_once_and_preserves_account(self):
        inactive = create_user(is_active=False)
        self.program.managers.add(inactive)
        self.accept()
        self.accept()
        self.assertEqual(ExpertJoinedNotification.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual({m.to[0] for m in mail.outbox}, {u.email for u in self.managers})
        self.assertIn("Анна Эксперт", mail.outbox[0].body)
        self.assertIn(
            f"/office/program/{self.program.pk}/management/experts", mail.outbox[0].body
        )
        for notice in ExpertJoinedNotification.objects.all():
            send_expert_joined_notification(notice.pk)
        self.assertEqual(len(mail.outbox), 2)

    def test_visit_and_sign_in_alone_do_not_notify_or_accept(self):
        self.assertEqual(
            self.client.get(f"/evaluation/invitations/{self.token}/").status_code, 200
        )
        self.assertEqual(
            self.client.post(
                "/api/token/", {"email": self.expert.email, "password": "pass"}
            ).status_code,
            200,
        )
        self.assertFalse(ExpertJoinedNotification.objects.exists())

    def test_inbox_is_private_read_is_idempotent_and_removed_organizer_loses_access(self):
        self.accept()
        self.client.force_authenticate(self.managers[0])
        response = self.client.get(self.root)
        self.assertEqual(response.data["unread_count"], 1)
        self.assertIn("no-store", response["Cache-Control"])
        notice = response.data["results"][0]
        read = self.client.post(f"{self.root}{notice['id']}/read/", {}).data
        self.assertEqual(
            self.client.post(f"{self.root}{notice['id']}/read/", {}).data, read
        )
        self.assertEqual(self.client.get(self.root).data["unread_count"], 0)
        self.client.force_authenticate(self.managers[1])
        self.assertEqual(
            self.client.post(f"{self.root}{notice['id']}/read/", {}).status_code, 404
        )
        self.program.managers.remove(self.managers[0])
        self.client.force_authenticate(self.managers[0])
        self.assertEqual(self.client.get(self.root).data["results"], [])
        self.assertEqual(
            self.client.post(f"{self.root}{notice['id']}/read/", {}).status_code, 404
        )
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.root).status_code, 401)

    def test_rollback_does_not_create_notices_or_send_mail(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    accept_invitation(self.invitation, self.expert)
                    raise ValueError("rollback")
            except ValueError:
                pass
        self.assertFalse(ExpertJoinedNotification.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invited_registration_emits_receipt_and_retains_short_expert_form(self):
        self.invitation.email = "new-expert@example.com"
        self.invitation.save(update_fields=["email"])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/evaluation/invitations/{self.token}/register/",
                {
                    "first_name": "Новый",
                    "last_name": "Эксперт",
                    "password": "Qx!74Mrv29Zc",
                    "repeat_password": "Qx!74Mrv29Zc",
                    "accept_policy": True,
                    "accept_age": True,
                },
                format="json",
            )
        self.assertEqual(response.status_code, 201)
        self.invitation.refresh_from_db()
        self.assertIsNone(self.invitation.accepted_by.birthday)
        self.assertEqual(len(mail.outbox), 2)
