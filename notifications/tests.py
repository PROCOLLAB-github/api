from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import (
    Notification,
    NotificationChannelPreference,
    NotificationDelivery,
    TelegramAccount,
    TelegramLinkToken,
)
from notifications.services import (
    notify_expert_projects_assigned,
    notify_verification_approved,
    notify_verification_rejected,
    notify_verification_submitted,
)
from notifications.tasks import send_notification_email, send_telegram_notification
from notifications.telegram import TelegramRetryableError, token_hash
from partner_programs.models import PartnerProgram, PartnerProgramVerificationRequest
from partner_programs.verification_services import submit_verification_request
from projects.models import Company
from users.models import CustomUser


@override_settings(
    FRONTEND_URL="https://app.test",
    DEFAULT_FROM_EMAIL="from@test",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class NotificationMVPTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.now = timezone.now()
        self.staff = self.create_user("staff-notifications@example.com", is_staff=True)
        self.manager = self.create_user("manager-notifications@example.com")
        self.other_manager = self.create_user("other-manager-notifications@example.com")
        self.outsider = self.create_user("outsider-notifications@example.com")
        self.expert_user = self.create_user(
            "expert-notifications@example.com",
            user_type=CustomUser.EXPERT,
        )
        self.program = self.create_program()
        self.program.managers.add(self.manager)
        self.company = Company.objects.create(name="Official Company", inn="7707083893")

    def create_user(self, email: str, **extra_fields):
        defaults = {
            "password": "pass",
            "first_name": "Test",
            "last_name": "User",
            "birthday": "1990-01-01",
            "is_active": True,
        }
        defaults.update(extra_fields)
        return get_user_model().objects.create_user(email=email, **defaults)

    def create_program(self, **overrides):
        defaults = {
            "name": "Financial Foresight 2026",
            "tag": f"financial_{PartnerProgram.objects.count()}",
            "description": "Program description",
            "city": "Moscow",
            "data_schema": {},
            "status": PartnerProgram.STATUS_PUBLISHED,
            "verification_status": PartnerProgram.VERIFICATION_STATUS_NOT_REQUESTED,
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now + timezone.timedelta(days=10),
            "datetime_started": self.now + timezone.timedelta(days=20),
            "datetime_evaluation_ends": self.now + timezone.timedelta(days=35),
            "datetime_finished": self.now + timezone.timedelta(days=50),
        }
        defaults.update(overrides)
        return PartnerProgram.objects.create(**defaults)

    def verification_request(self, *, initiator=None, status="pending", **overrides):
        defaults = {
            "program": self.program,
            "company": self.company,
            "company_name": self.company.name,
            "inn": self.company.inn,
            "legal_name": 'OOO "Official Company"',
            "website": "https://official.example.com",
            "region": "Moscow",
            "initiator": initiator or self.manager,
            "contact_full_name": "Ivan Manager",
            "contact_position": "Lead",
            "contact_email": "lead@example.com",
            "contact_phone": "+79990000000",
            "company_role_description": "Company organizes the championship.",
            "status": status,
        }
        defaults.update(overrides)
        return PartnerProgramVerificationRequest.objects.create(**defaults)

    def assert_in_app_sent(self, notification):
        delivery = notification.deliveries.get(channel=NotificationDelivery.Channel.IN_APP)
        self.assertEqual(delivery.status, NotificationDelivery.Status.SENT)
        self.assertIsNotNone(delivery.sent_at)

    @patch("notifications.services.send_notification_email.delay")
    def test_verification_events_notify_staff_and_organizers(self, delay_mock):
        request = self.verification_request()

        with self.captureOnCommitCallbacks(execute=True):
            notify_verification_submitted(self.program, request)
            notify_verification_approved(request)

        submitted = Notification.objects.get(
            recipient=self.staff,
            type=Notification.Type.COMPANY_VERIFICATION_SUBMITTED,
        )
        approved = Notification.objects.get(
            recipient=self.manager,
            type=Notification.Type.COMPANY_VERIFICATION_APPROVED,
        )
        self.assertEqual(
            submitted.url,
            f"/office/admin/moderation/verification/{request.id}",
        )
        self.assertEqual(approved.url, f"/office/program/{self.program.id}/edit/verification")
        self.assert_in_app_sent(submitted)
        self.assert_in_app_sent(approved)
        self.assertEqual(delay_mock.call_count, 2)

    @patch("notifications.services.send_notification_email.delay")
    def test_verification_reject_notifies_manager_and_initiator_once_each(self, delay_mock):
        request = self.verification_request(
            initiator=self.other_manager,
            status=PartnerProgramVerificationRequest.STATUS_REJECTED,
            rejection_reason=PartnerProgramVerificationRequest.REJECTION_INSUFFICIENT_DOCUMENTS,
            admin_comment="Upload current documents.",
        )

        with self.captureOnCommitCallbacks(execute=True):
            created = notify_verification_rejected(request)

        self.assertEqual(created, 2)
        recipients = set(
            Notification.objects.filter(
                type=Notification.Type.COMPANY_VERIFICATION_REJECTED,
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(recipients, {self.manager.id, self.other_manager.id})
        self.assertEqual(delay_mock.call_count, 2)

    @patch("notifications.services.send_notification_email.delay")
    def test_submit_verification_request_triggers_notification(self, delay_mock):
        with self.captureOnCommitCallbacks(execute=True):
            request = submit_verification_request(
                program=self.program,
                author=self.manager,
                company=self.company,
                company_name=self.company.name,
                inn=self.company.inn,
                legal_name='OOO "Official Company"',
                ogrn="",
                website="https://official.example.com",
                region="Moscow",
                contact_full_name="Ivan Manager",
                contact_position="Lead",
                contact_email="lead@example.com",
                contact_phone="+79990000000",
                company_role_description="Company organizes the championship.",
                documents=[],
            )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.staff,
                type=Notification.Type.COMPANY_VERIFICATION_SUBMITTED,
                object_id=request.id,
            ).exists()
        )
        self.assertEqual(delay_mock.call_count, 1)

    @patch("notifications.services.send_notification_email.delay")
    def test_expert_assignment_creates_one_aggregated_notification(self, delay_mock):
        self.expert_user.expert.programs.add(self.program)

        with self.captureOnCommitCallbacks(execute=True):
            notify_expert_projects_assigned(
                program=self.program,
                expert=self.expert_user.expert,
                project_count=5,
                batch_key="batch-1",
                project_ids=[1, 2, 3, 4, 5],
            )
            notify_expert_projects_assigned(
                program=self.program,
                expert=self.expert_user.expert,
                project_count=5,
                batch_key="batch-1",
                project_ids=[1, 2, 3, 4, 5],
            )

        notifications = Notification.objects.filter(
            recipient=self.expert_user,
            type=Notification.Type.EXPERT_PROJECTS_ASSIGNED,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertIn("5 проектов", notifications.get().message)
        self.assertEqual(delay_mock.call_count, 1)

    @patch("notifications.services.send_notification_email.delay")
    def test_email_task_is_enqueued_only_on_commit(self, delay_mock):
        request = self.verification_request()

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_verification_submitted(self.program, request)
            self.assertFalse(delay_mock.called)

        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        self.assertTrue(delay_mock.called)

    @patch("notifications.services.send_notification_email.delay")
    def test_missing_preferences_default_to_enabled(self, delay_mock):
        self.staff.notification_preferences.delete()
        request = self.verification_request()

        with self.captureOnCommitCallbacks(execute=True):
            notify_verification_submitted(self.program, request)

        self.assertTrue(Notification.objects.filter(recipient=self.staff).exists())
        self.assertEqual(delay_mock.call_count, 1)

    @patch("notifications.services.send_notification_email.delay")
    def test_email_preference_can_disable_email_delivery(self, delay_mock):
        self.manager.notification_preferences.email_verification_results = False
        self.manager.notification_preferences.save()
        request = self.verification_request()

        with self.captureOnCommitCallbacks(execute=True):
            notify_verification_approved(request)

        notification = Notification.objects.get(recipient=self.manager)
        self.assertFalse(
            notification.deliveries.filter(
                channel=NotificationDelivery.Channel.EMAIL,
            ).exists()
        )
        self.assertEqual(delay_mock.call_count, 0)

    def test_preferences_are_created_and_can_be_updated(self):
        self.assertTrue(hasattr(self.manager, "notification_preferences"))

        self.client.force_authenticate(self.manager)
        response = self.client.patch(
            "/auth/users/me/notification-preferences/",
            {"email_verification_results": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.manager.notification_preferences.refresh_from_db()
        self.assertFalse(self.manager.notification_preferences.email_verification_results)

    def test_api_isolation_unread_count_mark_read_and_mark_all(self):
        own = Notification.objects.create(
            recipient=self.manager,
            type=Notification.Type.COMPANY_VERIFICATION_APPROVED,
            title="Own",
            message="Own notification",
            object_type="verification_request",
            object_id=1,
            url=f"/office/program/{self.program.id}/edit/verification",
            dedupe_key="own",
        )
        Notification.objects.create(
            recipient=self.outsider,
            type=Notification.Type.COMPANY_VERIFICATION_APPROVED,
            title="Other",
            message="Other notification",
            object_type="verification_request",
            object_id=2,
            url=f"/office/program/{self.program.id}/edit/verification",
            dedupe_key="other",
        )

        self.client.force_authenticate(self.manager)
        response = self.client.get("/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], own.id)

        response = self.client.get("/notifications/unread-count/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        response = self.client.post(f"/notifications/{own.id}/read/")
        self.assertEqual(response.status_code, 200)
        own.refresh_from_db()
        self.assertTrue(own.is_read)

        own.is_read = False
        own.save(update_fields=["is_read"])
        response = self.client.post("/notifications/mark-all-read/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 1)
        own.refresh_from_db()
        self.assertTrue(own.is_read)

    def test_email_task_uses_plain_text_when_html_template_is_missing(self):
        notification = Notification.objects.create(
            recipient=self.manager,
            type=Notification.Type.COMPANY_VERIFICATION_APPROVED,
            title="Title",
            message="Message",
            object_type="verification_request",
            object_id=1,
            url=f"/office/program/{self.program.id}/edit/verification",
            dedupe_key="plain-fallback",
        )
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel=NotificationDelivery.Channel.EMAIL,
            status=NotificationDelivery.Status.PENDING,
        )

        result = send_notification_email(
            delivery.id,
            "Fallback subject",
            "email/notifications/missing-template.html",
            {"message": "Plain fallback message"},
            "Plain fallback message",
        )

        delivery.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(delivery.status, NotificationDelivery.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].body, "Plain fallback message")


@override_settings(
    FRONTEND_URL="https://app.test",
    SITE_URL="https://app.test",
    TELEGRAM_BOT_TOKEN="telegram-token",
    TELEGRAM_BOT_USERNAME="procollab_demo_bot",
    TELEGRAM_WEBHOOK_SECRET="webhook-secret",
    TELEGRAM_NOTIFICATIONS_ENABLED=True,
    TELEGRAM_ADMIN_CHAT_IDS=["123456"],
    DEFAULT_FROM_EMAIL="from@test",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class TelegramNotificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.now = timezone.now()
        self.staff = self.create_user("telegram-staff@example.com", is_staff=True)
        self.manager = self.create_user("telegram-manager@example.com")
        self.program = PartnerProgram.objects.create(
            name="Telegram Program",
            tag="telegram-program",
            description="Program description",
            city="Moscow",
            data_schema={},
            status=PartnerProgram.STATUS_PUBLISHED,
            verification_status=PartnerProgram.VERIFICATION_STATUS_NOT_REQUESTED,
            projects_availability="all_users",
            datetime_registration_ends=self.now + timezone.timedelta(days=10),
            datetime_started=self.now + timezone.timedelta(days=20),
            datetime_evaluation_ends=self.now + timezone.timedelta(days=35),
            datetime_finished=self.now + timezone.timedelta(days=50),
        )
        self.program.managers.add(self.manager)
        self.company = Company.objects.create(name="Telegram Company", inn="7707083893")

    def create_user(self, email: str, **extra_fields):
        defaults = {
            "password": "pass",
            "first_name": "Test",
            "last_name": "User",
            "birthday": "1990-01-01",
            "is_active": True,
        }
        defaults.update(extra_fields)
        return get_user_model().objects.create_user(email=email, **defaults)

    def verification_request(self):
        return PartnerProgramVerificationRequest.objects.create(
            program=self.program,
            company=self.company,
            company_name=self.company.name,
            inn=self.company.inn,
            legal_name='OOO "Telegram Company"',
            website="https://official.example.com",
            region="Moscow",
            initiator=self.manager,
            contact_full_name="Ivan Manager",
            contact_position="Lead",
            contact_email="lead@example.com",
            contact_phone="+79990000000",
            company_role_description="Company organizes the championship.",
            status=PartnerProgramVerificationRequest.STATUS_PENDING,
        )

    def _create_link(self, user):
        self.client.force_authenticate(user)
        response = self.client.post("/auth/users/me/telegram-link/")
        self.assertEqual(response.status_code, 201)
        token = response.data["token"]
        self.assertEqual(parse_qs(urlparse(response.data["link"]).query)["start"][0], token)
        self.assertEqual(response.data["bot_url"], "https://t.me/procollab_demo_bot")
        return token, response

    def test_link_token_is_hashed_and_start_binds_account(self):
        raw_token, response = self._create_link(self.manager)

        self.assertIn("https://t.me/procollab_demo_bot", response.data["link"])
        self.assertFalse(TelegramLinkToken.objects.filter(token_hash=raw_token).exists())
        self.assertTrue(
            TelegramLinkToken.objects.filter(token_hash=token_hash(raw_token)).exists()
        )

        response = self.client.post(
            "/telegram/webhook/",
            {
                "message": {
                    "text": f"/start {raw_token}",
                    "chat": {"id": 9000000001},
                    "from": {"username": "manager_tg"},
                }
            },
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="webhook-secret",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["method"], "sendMessage")
        self.assertEqual(response.data["chat_id"], 9000000001)
        account = self.manager.telegram_account
        self.assertTrue(account.is_active)
        self.assertEqual(account.telegram_chat_id, 9000000001)
        self.assertEqual(account.telegram_username, "manager_tg")
        self.assertIsNotNone(TelegramLinkToken.objects.get().used_at)

    def test_start_without_token_prompts_for_manual_token(self):
        self._create_link(self.manager)

        response = self.client.post(
            "/telegram/webhook/",
            {
                "message": {
                    "text": "/start",
                    "chat": {"id": 9000000010},
                    "from": {"username": "manager_tg"},
                }
            },
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="webhook-secret",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["method"], "sendMessage")
        self.assertEqual(response.data["chat_id"], 9000000010)
        self.assertIn("Пришлите токен подключения", response.data["text"])
        self.assertFalse(hasattr(self.manager, "telegram_account"))

    def test_plain_token_message_binds_account(self):
        raw_token, _ = self._create_link(self.manager)

        response = self.client.post(
            "/telegram/webhook/",
            {
                "message": {
                    "text": raw_token,
                    "chat": {"id": 9000000011},
                    "from": {"username": "manager_manual_tg"},
                }
            },
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="webhook-secret",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["method"], "sendMessage")
        self.assertIn("Telegram подключен", response.data["text"])
        account = self.manager.telegram_account
        self.assertTrue(account.is_active)
        self.assertEqual(account.telegram_chat_id, 9000000011)
        self.assertEqual(account.telegram_username, "manager_manual_tg")
        self.assertIsNotNone(TelegramLinkToken.objects.get().used_at)

    @patch("notifications.management.commands.poll_telegram_updates.send_telegram_message")
    @patch("notifications.management.commands.poll_telegram_updates.telegram_api_post")
    def test_polling_command_processes_manual_token_message(self, api_post, send_message):
        raw_token, _ = self._create_link(self.manager)
        api_post.side_effect = [
            Mock(
                status_code=200,
                json=lambda: {"ok": True, "result": True},
                text='{"ok":true}',
            ),
            Mock(
                status_code=200,
                json=lambda: {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 100,
                            "message": {
                                "text": raw_token,
                                "chat": {"id": 9000000012},
                                "from": {"username": "manager_poll_tg"},
                            },
                        }
                    ],
                },
                text='{"ok":true}',
            ),
        ]

        call_command("poll_telegram_updates", "--once")

        account = self.manager.telegram_account
        self.assertTrue(account.is_active)
        self.assertEqual(account.telegram_chat_id, 9000000012)
        self.assertEqual(account.telegram_username, "manager_poll_tg")
        send_message.assert_called_once()
        self.assertIn("Telegram подключен", send_message.call_args.kwargs["text"])

    def test_expired_or_reused_token_does_not_bind_account(self):
        raw_token, _ = self._create_link(self.manager)
        TelegramLinkToken.objects.filter(token_hash=token_hash(raw_token)).update(
            expires_at=timezone.now() - timezone.timedelta(minutes=1)
        )

        response = self.client.post(
            "/telegram/webhook/",
            {"message": {"text": f"/start {raw_token}", "chat": {"id": 100}}},
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="webhook-secret",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["method"], "sendMessage")
        self.assertFalse(hasattr(self.manager, "telegram_account"))

    def test_stop_clears_account_and_disables_preferences(self):
        TelegramAccount.objects.create(
            user=self.manager,
            telegram_chat_id=100,
            telegram_username="manager_tg",
            is_active=True,
            linked_at=timezone.now(),
        )
        NotificationChannelPreference.objects.create(
            user=self.manager,
            channel=NotificationChannelPreference.Channel.TELEGRAM,
            event_type=Notification.Type.COMPANY_VERIFICATION_APPROVED,
            enabled=True,
        )

        response = self.client.post(
            "/telegram/webhook/",
            {"message": {"text": "/stop", "chat": {"id": 100}}},
            format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="webhook-secret",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["method"], "sendMessage")
        account = self.manager.telegram_account
        account.refresh_from_db()
        self.assertFalse(account.is_active)
        self.assertIsNone(account.telegram_chat_id)
        self.assertEqual(account.telegram_username, "")
        self.assertFalse(
            NotificationChannelPreference.objects.filter(
                user=self.manager,
                channel=NotificationChannelPreference.Channel.TELEGRAM,
                enabled=True,
            ).exists()
        )

    @patch("notifications.services.send_telegram_notification.delay")
    @patch("notifications.services.send_notification_email.delay")
    def test_product_notifications_use_linked_users_not_admin_chat_ids(
        self,
        _email_delay,
        telegram_delay,
    ):
        request = self.verification_request()

        with self.captureOnCommitCallbacks(execute=True):
            notify_verification_submitted(self.program, request)

        notification = Notification.objects.get(recipient=self.staff)
        self.assertFalse(
            notification.deliveries.filter(
                channel=NotificationDelivery.Channel.TELEGRAM
            ).exists()
        )
        telegram_delay.assert_not_called()

        TelegramAccount.objects.create(
            user=self.staff,
            telegram_chat_id=9000000002,
            is_active=True,
            linked_at=timezone.now(),
        )
        second_request = self.verification_request()

        with self.captureOnCommitCallbacks(execute=True):
            notify_verification_submitted(self.program, second_request)

        self.assertTrue(
            Notification.objects.get(
                recipient=self.staff,
                dedupe_key=f"verification:{second_request.id}:submitted",
            ).deliveries.filter(channel=NotificationDelivery.Channel.TELEGRAM).exists()
        )

    @patch("notifications.services.send_telegram_notification.delay")
    @patch("notifications.services.send_notification_email.delay")
    def test_disabled_event_preference_skips_telegram_delivery(
        self,
        _email_delay,
        telegram_delay,
    ):
        TelegramAccount.objects.create(
            user=self.manager,
            telegram_chat_id=9000000003,
            is_active=True,
            linked_at=timezone.now(),
        )
        NotificationChannelPreference.objects.create(
            user=self.manager,
            channel=NotificationChannelPreference.Channel.TELEGRAM,
            event_type=Notification.Type.COMPANY_VERIFICATION_APPROVED,
            enabled=False,
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_verification_approved(self.verification_request())

        notification = Notification.objects.get(recipient=self.manager)
        self.assertFalse(
            notification.deliveries.filter(
                channel=NotificationDelivery.Channel.TELEGRAM
            ).exists()
        )
        telegram_delay.assert_not_called()

    @patch("notifications.telegram.requests.post")
    def test_successful_telegram_task_saves_provider_message_id(self, post_mock):
        TelegramAccount.objects.create(
            user=self.manager,
            telegram_chat_id=9000000004,
            is_active=True,
            linked_at=timezone.now(),
        )
        notification = Notification.objects.create(
            recipient=self.manager,
            type=Notification.Type.PROGRAM_MODERATION_APPROVED,
            title="Title",
            message="Sensitive details should not be sent to Telegram",
            object_type="moderation_log",
            object_id=1,
            url="/office/program/1",
            dedupe_key="telegram-success",
        )
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel=NotificationDelivery.Channel.TELEGRAM,
        )
        post_mock.return_value = Mock(
            status_code=200,
            json=lambda: {"ok": True, "result": {"message_id": 321}},
            text='{"ok":true}',
        )

        result = send_telegram_notification(delivery.id)

        delivery.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(delivery.status, NotificationDelivery.Status.SENT)
        self.assertEqual(delivery.provider_message_id, "321")
        self.assertEqual(delivery.attempts, 1)
        payload = post_mock.call_args.kwargs["json"]
        self.assertNotIn("Sensitive details", payload["text"])

    @patch("notifications.telegram.requests.post")
    def test_retryable_telegram_error_keeps_delivery_pending(self, post_mock):
        TelegramAccount.objects.create(
            user=self.manager,
            telegram_chat_id=9000000005,
            is_active=True,
            linked_at=timezone.now(),
        )
        notification = Notification.objects.create(
            recipient=self.manager,
            type=Notification.Type.PROGRAM_MODERATION_APPROVED,
            title="Title",
            message="Message",
            object_type="moderation_log",
            object_id=1,
            url="/office/program/1",
            dedupe_key="telegram-retry",
        )
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel=NotificationDelivery.Channel.TELEGRAM,
        )
        post_mock.return_value = Mock(
            status_code=429,
            json=lambda: {"parameters": {"retry_after": 1}},
            text='{"retry_after":1}',
        )

        with self.assertRaises(TelegramRetryableError):
            send_telegram_notification(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)
        self.assertEqual(delivery.attempts, 1)
        self.assertIn("rate limit", delivery.last_error.lower())

    @patch("notifications.telegram.requests.post")
    def test_permanent_telegram_error_fails_without_infinite_retry(self, post_mock):
        TelegramAccount.objects.create(
            user=self.manager,
            telegram_chat_id=9000000006,
            is_active=True,
            linked_at=timezone.now(),
        )
        notification = Notification.objects.create(
            recipient=self.manager,
            type=Notification.Type.PROGRAM_MODERATION_APPROVED,
            title="Title",
            message="Message",
            object_type="moderation_log",
            object_id=1,
            url="/office/program/1",
            dedupe_key="telegram-permanent",
        )
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel=NotificationDelivery.Channel.TELEGRAM,
        )
        post_mock.return_value = Mock(
            status_code=403,
            json=lambda: {"ok": False},
            text='{"ok":false}',
        )

        result = send_telegram_notification(delivery.id)

        delivery.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(delivery.status, NotificationDelivery.Status.FAILED)
        self.assertEqual(delivery.attempts, 1)
