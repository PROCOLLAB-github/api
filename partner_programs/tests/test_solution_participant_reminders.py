from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from partner_programs.models import (
    ProgramAttentionReminder,
    ProgramAttentionReminderBatch,
)
from partner_programs.services.attention_actions import deliver_reminder
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)

TEAMS = "participants-without-team"
VISITS = "participants-without-visit"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EXPERT_WORKSPACE_FRONTEND_URL="https://procollab.local",
)
class SolutionParticipantRemindersTests(TestCase):
    def setUp(self):
        self.manager = create_user()
        self.program = create_partner_program(
            solution_storage_mode="solution", solution_template="case_championship"
        )
        self.program.managers.add(self.manager)
        self.captain = self.registered()
        self.solution = ProgramSolution.objects.create(
            program=self.program, captain=self.captain
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def registered(self, program=None, **fields):
        user = create_user(**fields)
        create_program_member(program or self.program, user=user)
        return user

    def post(self, action, payload, category=TEAMS, program=None):
        return self.client.post(
            f"/programs/{(program or self.program).pk}/manager-overview/"
            f"attention/{category}/{action}/",
            payload,
            format="json",
        )

    def preview(self, ids=None, category=TEAMS):
        response = self.post(
            "reminder-preview",
            {
                "selection": {
                    "mode": "all" if ids is None else "selected",
                    "ids": ids or [],
                    "excluded_ids": [],
                }
            },
            category,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        return response.data

    def confirm(self, preview, category=TEAMS):
        response = self.post("reminders", {"token": preview["token"]}, category)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        return response.data

    def test_preview_uses_accepted_membership_and_real_program_scope(self):
        member = self.registered()
        ProgramSolutionMember.objects.create(solution=self.solution, user=member)
        pending = self.registered()
        SolutionInvitation.objects.create(solution=self.solution, recipient=pending)
        without_team = self.registered()
        historical = create_project(leader=without_team)
        create_program_project(self.program, project=historical)
        other_program = create_partner_program(solution_storage_mode="solution")
        self.registered(other_program)

        result = self.preview()

        self.assertEqual(result["selected_count"], 2)
        self.assertEqual(result["recipient_count"], 2)
        self.assertCountEqual(
            [row["user_id"] for row in result["recipients"]],
            [pending.pk, without_team.pk],
        )
        self.assertIn(
            "Создайте решение или присоединитесь к команде.", result["preview_text"]
        )
        self.assertNotIn("Создайте проект", result["preview_text"])
        self.assertFalse(ProgramAttentionReminderBatch.objects.exists())
        self.assertFalse(ProgramAttentionReminder.objects.exists())

    def test_template_competition_and_legacy_keep_their_participant_message(self):
        self.registered()
        for template, competitive in [
            ("case_championship", True),
            ("hackathon", True),
            ("hackathon", False),
        ]:
            with self.subTest(template=template, competitive=competitive):
                self.program.solution_template = template
                self.program.is_competitive = competitive
                self.program.save(update_fields=["solution_template", "is_competitive"])
                self.assertIn("Создайте решение", self.preview()["preview_text"])

        legacy = create_partner_program()
        legacy.managers.add(self.manager)
        user = self.registered(legacy)
        response = self.post(
            "reminder-preview",
            {"selection": {"mode": "selected", "ids": [user.pk]}},
            program=legacy,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("Создайте проект", response.data["preview_text"])
        self.assertNotIn("Создайте решение", response.data["preview_text"])

    def test_confirm_is_idempotent_and_queues_only_after_commit(self):
        user = self.registered()
        preview = self.preview([user.pk])
        with patch("partner_programs.services.attention_actions.queue_batch") as queue:
            with self.captureOnCommitCallbacks(execute=True):
                result = self.confirm(preview)
                queue.assert_not_called()
            queue.assert_called_once()
            self.assertEqual(self.confirm(preview), result)
            queue.assert_called_once()

        self.assertEqual(result, {"created_count": 1, "skipped_count": 0})
        notice = ProgramAttentionReminder.objects.get()
        self.assertEqual(notice.recipient_id, user.pk)
        self.assertEqual(notice.source_ids, [user.pk])
        self.assertEqual(notice.assignment_ids, [])
        self.assertEqual(notice.text, preview["preview_text"])
        self.assertEqual(notice.action_path, f"/office/program/{self.program.pk}/members")

    def test_member_joining_after_preview_is_excluded_at_confirmation(self):
        user = self.registered()
        preview = self.preview([user.pk])
        ProgramSolutionMember.objects.create(solution=self.solution, user=user)

        self.assertEqual(self.confirm(preview), {"created_count": 0, "skipped_count": 1})
        self.assertFalse(ProgramAttentionReminder.objects.exists())

    def test_captain_creating_solution_after_confirmation_cancels_delivery(self):
        user = self.registered()
        self.confirm(self.preview([user.pk]))
        notice = ProgramAttentionReminder.objects.get()
        ProgramSolution.objects.create(program=self.program, captain=user)

        deliver_reminder(notice.pk)

        notice.refresh_from_db()
        self.assertEqual(notice.delivery_status, "cancelled")
        self.assertEqual(notice.attempts, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_local_delivery_preserves_solution_text_path_and_exactly_one_email(self):
        user = self.registered()
        self.confirm(self.preview([user.pk]))
        notice = ProgramAttentionReminder.objects.get()

        deliver_reminder(notice.pk)
        deliver_reminder(notice.pk)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertIn("Создайте решение", mail.outbox[0].body)
        self.assertNotIn("Создайте проект", mail.outbox[0].body)
        self.assertIn(
            f"https://procollab.local/office/program/{self.program.pk}/members",
            mail.outbox[0].body,
        )
        notice.refresh_from_db()
        self.assertEqual(notice.delivery_status, "sent")
        self.assertEqual(notice.attempts, 1)
        self.assertIsNotNone(notice.emailed_at)

    def test_visit_reminder_retains_program_path_and_no_team_instruction(self):
        user = self.registered()
        preview = self.preview([user.pk], VISITS)
        self.assertIn("Зайдите на PROCOLLAB", preview["preview_text"])
        self.assertNotIn("Создайте", preview["preview_text"])
        self.confirm(preview, VISITS)
        self.assertEqual(
            ProgramAttentionReminder.objects.get().action_path,
            f"/office/program/{self.program.pk}",
        )

    def test_direct_solution_api_requires_manager_for_this_program(self):
        participant, stranger = self.registered(), create_user()
        for actor, status in [(None, 401), (participant, 403), (stranger, 403)]:
            self.client.force_authenticate(actor)
            for action in ["reminder-preview", "reminders"]:
                with self.subTest(actor=actor, action=action):
                    self.assertEqual(self.post(action, {}).status_code, status)

        self.client.force_authenticate(self.manager)
        other = create_partner_program(solution_storage_mode="solution")
        self.assertEqual(
            self.post("reminder-preview", {}, program=other).status_code, 403
        )
        self.client.force_authenticate(create_user(is_staff=True))
        self.assertEqual(self.preview([participant.pk])["recipient_count"], 1)
        self.assertFalse(ProgramAttentionReminder.objects.exists())
