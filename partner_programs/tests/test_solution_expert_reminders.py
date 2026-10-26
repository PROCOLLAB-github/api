import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.core import mail, signing
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    ProgramAttentionReminder,
    ProgramAttentionReminderBatch,
)
from partner_programs.services.attention_actions import (
    SALT,
    confirm_reminder,
    deliver_reminder,
    preview_reminder,
)
from partner_programs.services.solution_attention import SOLUTION_AWAITING
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_models import ProgramSolution
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_user,
)
from partner_programs.tests.test_solution_forms import call
from project_rates.models import Criteria, ProjectExpertAssignment
from project_rates.solution_evaluation import snapshot_name
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.tests.test_solution_evaluation import EvaluationFixture
from project_rates.tests.helpers import create_rate_expert
from projects.models import Project


class ReminderFixture(EvaluationFixture):
    def seed_reminder(self):
        self.seed_evaluation()
        self.reminder_url = (
            f"/programs/{self.program.pk}/management/solution-analytics/"
            "attention/solutions-awaiting-evaluation/"
        )

    def selection(self, ids=None, *, search="", excluded=None):
        return dict(
            search=search,
            selection=dict(
                mode="all" if ids is None else "selected",
                ids=ids or [],
                excluded_ids=excluded or [],
            ),
        )

    def preview(self, payload=None):
        response = call(
            self.manager,
            "post",
            self.reminder_url + "reminder-preview/",
            payload or self.selection(),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assert_schema("SolutionReminderPreview", response.data)
        return response.data

    def confirm(self, preview):
        response = call(
            self.manager,
            "post",
            self.reminder_url + "reminders/",
            dict(token=preview["token"]),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assert_schema("SolutionReminderReceipt", response.data)
        return response.data

    def assign(self, solution, expert=None):
        return SolutionExpertAssignment.objects.create(
            partner_program=self.program,
            solution=solution,
            expert=(expert or self.expert).expert,
        )

    def complete(self, solution=None, expert=None):
        for criterion, value in zip(self.criteria, ["0", "False", ""]):
            SolutionScore.objects.create(
                solution=solution or self.solution,
                criteria=criterion,
                user=expert or self.expert,
                value=value,
            )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EXPERT_WORKSPACE_FRONTEND_URL="https://procollab.local",
)
class SolutionExpertRemindersTests(ReminderFixture, TestCase):
    def setUp(self):
        self.seed_reminder()

    def test_preview_is_private_read_only_scoped_and_deduplicates_real_expert(self):
        second = self.another_solution()
        self.assign(second)
        self.another_solution(submitted=False)
        unassigned = self.another_solution()
        other = create_partner_program(solution_storage_mode="solution")
        foreign_snapshot = copy.deepcopy(self.solution.submission_snapshot)
        foreign_snapshot["program_id"] = other.pk
        foreign = ProgramSolution.objects.create(
            program=other,
            captain=self.captain,
            status="submitted",
            submitted_at=timezone.now(),
            submission_snapshot=foreign_snapshot,
        )

        result = self.preview()

        self.assertEqual(result["selected_count"], 3)
        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(result["without_assignments_count"], 1)
        self.assertEqual(result["unavailable_count"], 0)
        self.assertEqual(result["recipients"][0]["user_id"], self.expert.pk)
        self.assertNotIn("email", result["recipients"][0])
        token = signing.loads(result["token"], salt=SALT)
        self.assertCountEqual(
            token["source_ids"], [self.solution.pk, second.pk, unassigned.pk]
        )
        self.assertNotIn(foreign.pk, token["source_ids"])
        self.assertFalse(ProgramAttentionReminderBatch.objects.exists())
        self.assertFalse(ProgramAttentionReminder.objects.exists())

    def test_search_uses_snapshot_and_selection_excludes_other_found_rows(self):
        name = snapshot_name(self.solution)
        ProgramSolution.objects.filter(pk=self.solution.pk).update(name="Другое имя")
        second = self.another_solution()
        self.assign(second)
        result = self.preview(self.selection(search=name))
        self.assertEqual(result["selected_count"], 1)
        self.assertIn(f"«{name}»", result["preview_text"])
        self.assertNotIn("Другое имя", result["preview_text"])
        result = self.preview(self.selection(excluded=[self.solution.pk]))
        self.assertEqual(result["selected_count"], 1)
        self.assertIn(f"«{snapshot_name(second)}»", result["preview_text"])
        result = self.preview(self.selection([self.solution.pk]))
        self.assertEqual(result["selected_count"], 1)

    def test_all_selection_is_not_limited_to_first_twenty_solutions(self):
        for _ in range(25):
            self.assign(self.another_solution())
        result = self.preview(self.selection(excluded=[self.solution.pk]))
        self.assertEqual(result["selected_count"], 25)
        self.assertEqual(result["recipient_count"], 1)
        token = signing.loads(result["token"], salt=SALT)
        self.assertEqual(len(token["source_ids"]), 25)
        self.assertNotIn(self.solution.pk, token["source_ids"])

    def test_recipient_preview_is_limited_but_approved_count_is_complete(self):
        self.program.required_evaluators = 21
        self.program.save(update_fields=["required_evaluators"])
        for _ in range(20):
            self.assign(self.solution, create_rate_expert(program=self.program))
        result = self.preview()
        self.assertEqual(result["recipient_count"], 21)
        self.assertEqual(len(result["recipients"]), 20)
        self.assertEqual(len(signing.loads(result["token"], salt=SALT)["targets"]), 21)

    def test_other_program_missing_program_and_cross_program_token_are_rejected(self):
        other = create_partner_program(
            solution_storage_mode="solution",
            is_distributed_evaluation=True,
            is_competitive=True,
        )
        url = self.reminder_url.replace(f"/{self.program.pk}/", f"/{other.pk}/")
        response = call(self.manager, "post", url + "reminder-preview/", self.selection())
        self.assertEqual(response.status_code, 403)
        self.assert_schema("Error", response.data)
        other.managers.add(self.manager)
        preview = self.preview()
        response = call(
            self.manager, "post", url + "reminders/", dict(token=preview["token"])
        )
        self.assertEqual(response.status_code, 400)
        self.assert_schema("Error", response.data)
        missing_url = self.reminder_url.replace(f"/{self.program.pk}/", f"/{MAX_ID}/")
        response = call(
            self.manager, "post", missing_url + "reminder-preview/", self.selection()
        )
        self.assertEqual(response.status_code, 404)
        self.assert_schema("Error", response.data)

    def test_full_zero_false_and_empty_comment_are_completed(self):
        self.complete()
        result = self.preview()
        self.assertEqual(result["selected_count"], 0)
        self.assertEqual(result["recipient_count"], 0)
        self.assertIsNone(result["token"])

    def test_partial_or_invalid_scores_keep_assignment_unfinished(self):
        score = SolutionScore.objects.create(
            criteria=self.criteria[0], user=self.expert, solution=self.solution, value="0"
        )
        self.assertEqual(self.preview()["recipient_count"], 1)
        self.complete(expert=self.second)
        SolutionScore.objects.filter(pk=score.pk).update(value="NaN")
        self.assertEqual(self.preview()["recipient_count"], 1)

    def test_quota_uses_analytics_state_and_only_pending_expert_is_targeted(self):
        self.program.required_evaluators = 2
        self.program.save(update_fields=["required_evaluators"])
        self.assign(self.solution, self.second)
        self.complete()
        result = self.preview()
        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(result["recipients"][0]["user_id"], self.second.pk)
        self.program.required_evaluators = 1
        self.program.save(update_fields=["required_evaluators"])
        self.assertEqual(self.preview()["selected_count"], 0)

    def test_no_criteria_does_not_turn_assignment_into_completed(self):
        Criteria.objects.filter(partner_program=self.program).delete()
        self.assertEqual(self.preview()["recipient_count"], 1)

    def test_unassigned_missing_email_and_inactive_are_distinct(self):
        self.assignment.delete()
        unassigned = self.preview()
        self.assertEqual(unassigned["without_assignments_count"], 1)
        self.assertEqual(unassigned["unavailable_count"], 0)
        self.assign(self.solution)
        type(self.expert).objects.filter(pk=self.expert.pk).update(email="")
        missing = self.preview()
        self.assertEqual(missing["without_assignments_count"], 0)
        self.assertEqual(missing["unavailable_count"], 1)
        self.assertIsNone(missing["token"])
        type(self.expert).objects.filter(pk=self.expert.pk).update(is_active=False)
        inactive = self.preview()
        self.assertEqual(inactive["without_assignments_count"], 1)
        self.assertEqual(inactive["unavailable_count"], 0)

    def test_direct_api_program_permissions_modes_and_errors(self):
        for suffix in ["reminder-preview/", "reminders/"]:
            for actor, status in [
                (self.captain, 403),
                (self.expert, 403),
                (create_user(), 403),
            ]:
                response = call(actor, "post", self.reminder_url + suffix, {})
                self.assertEqual(response.status_code, status)
                self.assert_schema("Error", response.data)
            response = APIClient().post(self.reminder_url + suffix, {}, format="json")
            self.assertEqual(response.status_code, 401)
            self.assert_schema("Error", response.data)
        staff = create_user(is_staff=True)
        self.assertEqual(
            call(
                staff, "post", self.reminder_url + "reminder-preview/", self.selection()
            ).status_code,
            200,
        )
        legacy = create_partner_program()
        legacy.managers.add(self.manager)
        url = self.reminder_url.replace(f"/{self.program.pk}/", f"/{legacy.pk}/")
        self.assertEqual(
            call(self.manager, "post", url + "reminder-preview/", self.selection()).data[
                "code"
            ],
            "solution_mode_unavailable",
        )
        self.program.is_distributed_evaluation = False
        self.program.save(update_fields=["is_distributed_evaluation"])
        response = call(
            self.manager,
            "post",
            self.reminder_url + "reminder-preview/",
            self.selection(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "reminders_not_applicable")
        self.program.is_competitive = False
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_competitive", "is_distributed_evaluation"])
        self.assertEqual(
            call(
                self.manager,
                "post",
                self.reminder_url + "reminder-preview/",
                self.selection(),
            ).status_code,
            409,
        )

    def test_strict_selection_safe_ids_query_and_max_found_validation(self):
        invalid = [
            {"selection": {"mode": "selected", "ids": []}},
            {"selection": {"mode": "all", "ids": [self.solution.pk]}},
            {"selection": {"mode": "selected", "ids": [0]}},
            {"selection": {"mode": "selected", "ids": [MAX_ID + 1]}},
            {"selection": {"mode": "selected", "ids": [1] * 10001}},
            {"selection": {"mode": "all", "unknown": True}},
            {"selection": {"mode": "all"}, "project_id": self.solution.pk},
        ]
        for payload in invalid:
            response = call(
                self.manager, "post", self.reminder_url + "reminder-preview/", payload
            )
            self.assertEqual(response.status_code, 400, response.data)
            self.assert_schema("Error", response.data)
        response = call(
            self.manager,
            "post",
            self.reminder_url + "reminder-preview/?unknown=1",
            self.selection(),
        )
        self.assertEqual(response.status_code, 400)
        with patch("partner_programs.services.solution_attention.MAX_SELECTION", 0):
            response = call(
                self.manager,
                "post",
                self.reminder_url + "reminder-preview/",
                self.selection(),
            )
        self.assertEqual(response.status_code, 400)

    def test_token_tampering_expiry_actor_and_other_category_are_rejected(self):
        preview = self.preview()
        for token in [preview["token"] + "tamper", "not-signed"]:
            self.assertEqual(
                call(
                    self.manager,
                    "post",
                    self.reminder_url + "reminders/",
                    dict(token=token),
                ).status_code,
                400,
            )
        with patch(
            "partner_programs.services.attention_actions.signing.loads",
            side_effect=signing.SignatureExpired,
        ):
            self.assertEqual(
                call(
                    self.manager,
                    "post",
                    self.reminder_url + "reminders/",
                    dict(token=preview["token"]),
                ).status_code,
                400,
            )
        other = create_user()
        self.program.managers.add(other)
        self.assertEqual(
            call(
                other,
                "post",
                self.reminder_url + "reminders/",
                dict(token=preview["token"]),
            ).status_code,
            400,
        )
        user = create_user()
        create_program_member(self.program, user=user)
        other_preview = preview_reminder(
            self.program,
            "participants-without-team",
            self.manager,
            self.selection([user.pk]),
        )
        self.assertEqual(
            call(
                self.manager,
                "post",
                self.reminder_url + "reminders/",
                dict(token=other_preview["token"]),
            ).status_code,
            400,
        )
        self.assertFalse(ProgramAttentionReminder.objects.exists())

    def test_confirmation_rechecks_completed_and_replaced_assignment(self):
        preview = self.preview()
        self.assignment.delete()
        self.assign(self.solution)
        self.assertEqual(self.confirm(preview), {"created_count": 0, "skipped_count": 1})
        fresh = self.preview()
        self.complete()
        self.assertEqual(self.confirm(fresh), {"created_count": 0, "skipped_count": 1})
        self.assertFalse(ProgramAttentionReminder.objects.exists())

    def test_confirmation_is_durable_idempotent_after_commit_and_does_not_add_targets(
        self,
    ):
        self.program.required_evaluators = 2
        self.program.save(update_fields=["required_evaluators"])
        preview = self.preview()
        self.assign(self.solution, self.second)
        with patch("partner_programs.services.attention_actions.queue_batch") as queue:
            with self.captureOnCommitCallbacks(execute=True):
                result = self.confirm(preview)
                queue.assert_not_called()
            queue.assert_called_once()
            self.assertEqual(self.confirm(preview), result)
            queue.assert_called_once()
        self.assertEqual(result, {"created_count": 1, "skipped_count": 0})
        notice = ProgramAttentionReminder.objects.get()
        self.assertEqual(notice.recipient_id, self.expert.pk)
        self.assertEqual(notice.source_ids, [self.solution.pk])
        self.assertEqual(notice.assignment_ids, [self.assignment.pk])

    def test_rollback_removes_notice_and_does_not_enqueue(self):
        preview = self.preview()
        with patch("partner_programs.services.attention_actions.queue_batch") as queue:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    self.confirm(preview)
                    transaction.set_rollback(True)
            queue.assert_not_called()
        self.assertFalse(ProgramAttentionReminderBatch.objects.exists())
        self.assertFalse(ProgramAttentionReminder.objects.exists())

    def test_platform_notice_is_owned_by_the_actual_assigned_expert(self):
        self.confirm(self.preview())
        notice = ProgramAttentionReminder.objects.get()
        feed = call(self.expert, "get", "/core/notifications/")
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(
            len(
                [
                    row
                    for row in feed.data["results"]
                    if row["kind"] == "program_attention"
                ]
            ),
            1,
        )
        read_url = f"/core/notifications/program_attention:{notice.pk}/read/"
        self.assertEqual(call(self.manager, "post", read_url, {}).status_code, 404)
        self.assertEqual(call(self.expert, "post", read_url, {}).status_code, 200)

    def test_delivery_uses_only_remaining_approved_work_and_real_solution_route(self):
        second = self.another_solution()
        other_assignment = self.assign(second)
        self.confirm(self.preview())
        notice = ProgramAttentionReminder.objects.get()
        other_assignment.delete()
        self.assign(second)
        deliver_reminder(notice.pk)
        deliver_reminder(notice.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.expert.email])
        self.assertIn(f"«{snapshot_name(self.solution)}»", mail.outbox[0].body)
        self.assertNotIn(f"«{snapshot_name(second)}»", mail.outbox[0].body)
        self.assertIn(
            f"https://procollab.local/office/program/{self.program.pk}/solutions-rating",
            mail.outbox[0].body,
        )
        self.assertNotIn("/projects-rating", mail.outbox[0].body)
        notice.refresh_from_db()
        self.assertEqual(notice.delivery_status, "sent")
        self.assertEqual(notice.attempts, 1)

    def test_delivery_cancels_when_expert_finishes_or_leaves_program(self):
        self.confirm(self.preview())
        notice = ProgramAttentionReminder.objects.get()
        self.expert.expert.programs.remove(self.program)
        deliver_reminder(notice.pk)
        notice.refresh_from_db()
        self.assertEqual(notice.delivery_status, "cancelled")
        self.assertEqual(len(mail.outbox), 0)

    def test_delivery_cancels_after_completion_or_mode_switch(self):
        self.confirm(self.preview())
        first = ProgramAttentionReminder.objects.get()
        self.complete()
        deliver_reminder(first.pk)
        first.refresh_from_db()
        self.assertEqual(first.delivery_status, "cancelled")
        second = self.another_solution()
        self.assign(second)
        self.confirm(self.preview())
        last = ProgramAttentionReminder.objects.exclude(pk=first.pk).get()
        self.program.is_distributed_evaluation = False
        self.program.save(update_fields=["is_distributed_evaluation"])
        deliver_reminder(last.pk)
        last.refresh_from_db()
        self.assertEqual(last.delivery_status, "cancelled")
        self.assertEqual(len(mail.outbox), 0)

    def test_colliding_project_identity_and_legacy_assignments_are_not_targets(self):
        # Историческая проектная заявка могла существовать до включения solution mode.
        project = Project(
            id=self.solution.pk,
            leader=create_user(),
            name="Посторонний проект",
            description="Описание",
            draft=False,
            is_public=False,
        )
        Project.objects.bulk_create([project])
        create_program_project(self.program, project=project, submitted=True)
        ProjectExpertAssignment.objects.bulk_create(
            [
                ProjectExpertAssignment(
                    partner_program=self.program,
                    project=project,
                    expert=self.second.expert,
                )
            ]
        )
        result = self.preview()
        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(result["recipients"][0]["user_id"], self.expert.pk)
        self.assertNotIn("Посторонний проект", result["preview_text"])
        self.confirm(result)
        notice = ProgramAttentionReminder.objects.get()
        self.assertEqual(notice.assignment_ids, [self.assignment.pk])
        self.assertEqual(notice.source_ids, [self.solution.pk])


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL locks")
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionReminderConcurrencyTests(ReminderFixture, TransactionTestCase):
    def test_two_confirmations_create_one_batch_notice_and_queue(self):
        self.seed_reminder()
        preview = preview_reminder(
            self.program, SOLUTION_AWAITING, self.manager, self.selection()
        )
        barrier = Barrier(2)

        def confirm():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return confirm_reminder(
                    self.program, SOLUTION_AWAITING, self.manager, preview["token"]
                )
            finally:
                close_old_connections()

        with patch("partner_programs.services.attention_actions.queue_batch") as queue:
            with ThreadPoolExecutor(max_workers=2) as workers:
                first, second = list(workers.map(lambda _: confirm(), range(2)))
        self.assertEqual(first, second)
        self.assertEqual(first, {"created_count": 1, "skipped_count": 0})
        self.assertEqual(ProgramAttentionReminderBatch.objects.count(), 1)
        self.assertEqual(ProgramAttentionReminder.objects.count(), 1)
        queue.assert_called_once()
