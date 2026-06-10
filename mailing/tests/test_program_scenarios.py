from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from mailing.models import MailingScenarioLog
from mailing.tasks import run_program_mailings
from partner_programs.selectors import (
    program_participants_with_inactive_account,
    program_participants_with_inactive_account_registered_on,
)
from users.models import CustomUser

from .helpers import aware_datetime, create_program, create_user, register_program_user


class _SentStatus:
    def __init__(self, message_id: str, status="sent"):
        self.message_id = message_id
        self.status = status


class _SentMessage:
    def __init__(self, user_id: int, status="sent", message_id: str | None = None):
        self.anymail_status = _SentStatus(message_id or f"msg-{user_id}", status)


def _fake_send_mass_mail_from_template(
    users,
    subject,
    template_name,
    context_builder=None,
    status_callback=None,
):
    for user in users:
        if status_callback:
            status_callback(user, _SentMessage(user.id))
    return len(users)


def _fake_failed_send_mass_mail_from_template(
    users,
    subject,
    template_name,
    context_builder=None,
    status_callback=None,
):
    for user in users:
        if status_callback:
            status_callback(user, _SentMessage(user.id, status="rejected"))
    return len(users)


class ProgramInactiveAccountSelectorsTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()

    def test_participants_with_inactive_account(self):
        program = create_program()

        inactive_no_activity = create_user("inactive-no-activity@example.com")
        inactive_old_login = create_user("inactive-old-login@example.com")
        active_recent_activity = create_user("active-recent@example.com")

        register_program_user(
            inactive_no_activity, program, self.today - timedelta(days=4)
        )
        register_program_user(
            inactive_old_login, program, self.today - timedelta(days=4)
        )
        register_program_user(
            active_recent_activity, program, self.today - timedelta(days=4)
        )

        CustomUser.objects.filter(id=inactive_old_login.id).update(
            last_login=aware_datetime(self.today - timedelta(days=15))
        )
        CustomUser.objects.filter(id=active_recent_activity.id).update(
            last_activity=aware_datetime(self.today - timedelta(days=1))
        )

        recipients = program_participants_with_inactive_account(
            program.id, program.datetime_started
        )
        recipient_ids = set(recipients.values_list("id", flat=True))

        self.assertIn(inactive_no_activity.id, recipient_ids)
        self.assertIn(inactive_old_login.id, recipient_ids)
        self.assertNotIn(active_recent_activity.id, recipient_ids)

    def test_participants_with_inactive_account_registered_on_date(self):
        program = create_program()
        target_date = self.today - timedelta(days=3)

        registered_on_target = create_user("registered-on-target@example.com")
        registered_other_day = create_user("registered-other-day@example.com")

        register_program_user(registered_on_target, program, target_date)
        register_program_user(
            registered_other_day,
            program,
            self.today - timedelta(days=2),
        )

        recipients = program_participants_with_inactive_account_registered_on(
            program.id, target_date, program.datetime_started
        )
        recipient_ids = set(recipients.values_list("id", flat=True))

        self.assertIn(registered_on_target.id, recipient_ids)
        self.assertNotIn(registered_other_day.id, recipient_ids)


class ProgramInactiveAccountScenariosTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()

    @patch(
        "mailing.tasks.send_mass_mail_from_template",
        side_effect=_fake_send_mass_mail_from_template,
    )
    def test_registration_plus_3_inactive_account_scenario(self, send_mail_mock):
        target_registration_date = self.today - timedelta(days=3)

        program = create_program(
            name="FinFor",
            tag="finfor",
            datetime_registration_ends=aware_datetime(self.today + timedelta(days=20)),
            datetime_started=aware_datetime(self.today - timedelta(days=15)),
        )

        inactive_user = create_user("inactive-user@example.com")
        active_user = create_user("active-user@example.com")
        registered_other_day_user = create_user("other-day-user@example.com")

        register_program_user(inactive_user, program, target_registration_date)
        register_program_user(active_user, program, target_registration_date)
        register_program_user(
            registered_other_day_user,
            program,
            self.today - timedelta(days=2),
        )

        CustomUser.objects.filter(id=active_user.id).update(
            last_activity=aware_datetime(self.today - timedelta(days=1))
        )

        sent_count = run_program_mailings()
        self.assertEqual(sent_count, 1)

        sent_logs = MailingScenarioLog.objects.filter(
            scenario_code="program_registration_plus_3_inactive_account",
            program=program,
            scheduled_for=self.today,
            status=MailingScenarioLog.Status.SENT,
        )
        self.assertEqual(sent_logs.count(), 1)
        self.assertEqual(sent_logs.first().user_id, inactive_user.id)
        self.assertEqual(send_mail_mock.call_count, 1)

        second_run_sent_count = run_program_mailings()
        self.assertEqual(second_run_sent_count, 0)
        self.assertEqual(send_mail_mock.call_count, 1)

        all_logs = MailingScenarioLog.objects.filter(
            scenario_code="program_registration_plus_3_inactive_account",
            program=program,
            scheduled_for=self.today,
        )
        self.assertEqual(all_logs.count(), 1)
        self.assertEqual(
            all_logs.first().status,
            MailingScenarioLog.Status.SENT,
        )

    @patch(
        "mailing.tasks.send_mass_mail_from_template",
        side_effect=_fake_send_mass_mail_from_template,
    )
    def test_registration_end_plus_3_inactive_account_scenario(self, send_mail_mock):
        target_registration_end_date = self.today - timedelta(days=3)

        program = create_program(
            name="FinFor",
            tag="finfor",
            datetime_registration_ends=aware_datetime(target_registration_end_date),
            datetime_started=aware_datetime(self.today - timedelta(days=15)),
            datetime_finished=aware_datetime(self.today + timedelta(days=20)),
        )

        inactive_user = create_user("inactive-end-user@example.com")
        active_user = create_user("active-end-user@example.com")

        register_program_user(inactive_user, program, self.today - timedelta(days=10))
        register_program_user(active_user, program, self.today - timedelta(days=10))

        CustomUser.objects.filter(id=active_user.id).update(
            last_login=aware_datetime(self.today - timedelta(days=1))
        )

        sent_count = run_program_mailings()
        self.assertEqual(sent_count, 1)

        sent_logs = MailingScenarioLog.objects.filter(
            scenario_code="program_registration_end_plus_3_inactive_account",
            program=program,
            scheduled_for=self.today,
            status=MailingScenarioLog.Status.SENT,
        )
        self.assertEqual(sent_logs.count(), 1)
        self.assertEqual(sent_logs.first().user_id, inactive_user.id)
        self.assertEqual(send_mail_mock.call_count, 1)

        second_run_sent_count = run_program_mailings()
        self.assertEqual(second_run_sent_count, 0)
        self.assertEqual(send_mail_mock.call_count, 1)

        all_logs = MailingScenarioLog.objects.filter(
            scenario_code="program_registration_end_plus_3_inactive_account",
            program=program,
            scheduled_for=self.today,
        )
        self.assertEqual(all_logs.count(), 1)
        self.assertEqual(
            all_logs.first().status,
            MailingScenarioLog.Status.SENT,
        )

    @patch(
        "mailing.tasks.send_mass_mail_from_template",
        side_effect=_fake_failed_send_mass_mail_from_template,
    )
    def test_failed_provider_status_marks_scenario_log_failed(self, send_mail_mock):
        target_registration_date = self.today - timedelta(days=3)
        program = create_program(
            datetime_registration_ends=aware_datetime(self.today + timedelta(days=20)),
            datetime_started=aware_datetime(self.today - timedelta(days=15)),
        )
        inactive_user = create_user("inactive-failed@example.com")
        register_program_user(inactive_user, program, target_registration_date)

        sent_count = run_program_mailings()

        self.assertEqual(sent_count, 0)
        log = MailingScenarioLog.objects.get(
            scenario_code="program_registration_plus_3_inactive_account",
            program=program,
            scheduled_for=self.today,
            user=inactive_user,
        )
        self.assertEqual(log.status, MailingScenarioLog.Status.FAILED)
        self.assertIn("anymail_status=rejected", log.error)
        self.assertEqual(send_mail_mock.call_count, 1)
