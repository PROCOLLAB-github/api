from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    Evaluation,
    EvaluationScore,
    Submission,
    SubmissionExpertAssignment,
)
from partner_programs.services.submission_assignments import (
    AssignmentCompletedError,
    create_submission_assignment,
)
from partner_programs.services import (
    submission_assignments as submission_assignment_service,
)
from partner_programs.tests.helpers import create_partner_program, create_user
from project_rates.tests.helpers import create_rate_criteria, create_rate_expert


def throttle_settings(**rates):
    rest_framework = dict(settings.REST_FRAMEWORK)
    rest_framework["DEFAULT_THROTTLE_RATES"] = {
        **rest_framework.get("DEFAULT_THROTTLE_RATES", {}),
        **rates,
    }
    return rest_framework


class SubmissionAssignmentTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.manager = create_user(prefix="assignment-manager")
        self.other_manager = create_user(prefix="assignment-other-manager")
        self.outsider = create_user(prefix="assignment-outsider")
        self.staff = create_user(prefix="assignment-staff", is_staff=True)
        self.participant = create_user(prefix="assignment-participant")
        self.program = create_partner_program()
        self.other_program = create_partner_program()
        self.program.managers.add(self.manager)
        self.other_program.managers.add(self.other_manager)
        self.expert_user = create_rate_expert(
            prefix="assignment-expert",
            program=self.program,
        )
        self.expert = self.expert_user.expert
        self.other_expert_user = create_rate_expert(
            prefix="assignment-other-expert",
            program=self.other_program,
        )
        self.other_expert = self.other_expert_user.expert
        self.submission = self.create_submission()
        self.list_url = f"/programs/{self.program.pk}/submission-assignments/"

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.manager)

    def create_submission(
        self,
        *,
        program=None,
        participant=None,
        status=Submission.STATUS_SUBMITTED,
        title="Assignment solution",
    ):
        program = program or self.program
        participant = participant or self.participant
        application = Application.objects.create(
            program=program,
            user=participant,
            created_by=participant,
            status=Application.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        return Submission.objects.create(
            application=application,
            program=program,
            submitted_by=participant,
            title=title,
            status=status,
            submitted_at=(
                timezone.now()
                if status in (Submission.STATUS_SUBMITTED, Submission.STATUS_FINAL)
                else None
            ),
        )

    def create_assignment(self, **overrides):
        values = {
            "submission": self.submission,
            "expert": self.expert,
            "assigned_by": self.manager,
        }
        values.update(overrides)
        return SubmissionExpertAssignment.objects.create(**values)

    def create_payload(self, **overrides):
        payload = {
            "submission_id": self.submission.pk,
            "expert_id": self.expert.pk,
        }
        payload.update(overrides)
        return payload


class SubmissionAssignmentListAPITests(SubmissionAssignmentTestCase):
    def test_unauthenticated_user_gets_401(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 401)

    def test_program_manager_can_list_assignments(self):
        self.create_assignment()
        self.authenticate()

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_outsider_gets_403(self):
        self.authenticate(self.outsider)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 403)

    def test_staff_can_list_assignments(self):
        self.create_assignment()
        self.authenticate(self.staff)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_get_unknown_program_gets_404(self):
        self.authenticate()

        response = self.client.get(
            f"/programs/{self.program.pk + self.other_program.pk + 1000}/"
            "submission-assignments/"
        )

        self.assertEqual(response.status_code, 404)

    def test_post_unknown_program_gets_404(self):
        self.authenticate()

        response = self.client.post(
            f"/programs/{self.program.pk + self.other_program.pk + 1000}/"
            "submission-assignments/",
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_list_contains_only_requested_program(self):
        own_assignment = self.create_assignment()
        other_submission = self.create_submission(
            program=self.other_program,
            participant=create_user(prefix="other-program-participant"),
        )
        SubmissionExpertAssignment.objects.create(
            submission=other_submission,
            expert=self.other_expert,
            assigned_by=self.other_manager,
        )
        self.authenticate()

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [own_assignment.pk],
        )

    def test_list_includes_revoked_history_newest_first(self):
        older = self.create_assignment(
            status=SubmissionExpertAssignment.STATUS_REVOKED,
            revoked_by=self.manager,
            revoked_at=timezone.now(),
            revoke_reason="First episode",
        )
        newer = self.create_assignment(
            status=SubmissionExpertAssignment.STATUS_REVOKED,
            revoked_by=self.manager,
            revoked_at=timezone.now(),
            revoke_reason="Second episode",
        )
        self.authenticate()

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [newer.pk, older.pk],
        )

    def test_list_uses_project_limit_offset_pagination(self):
        for index in range(11):
            self.create_assignment(
                status=SubmissionExpertAssignment.STATUS_REVOKED,
                revoked_by=self.manager,
                revoked_at=timezone.now(),
                revoke_reason=f"History {index}",
            )
        self.authenticate()

        first_page = self.client.get(self.list_url)
        second_page = self.client.get(self.list_url, {"offset": 10})

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.data["count"], 11)
        self.assertEqual(len(first_page.data["results"]), 10)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data["results"]), 1)

    def test_submission_expert_and_status_filters_work(self):
        matching = self.create_assignment()
        second_expert_user = create_rate_expert(
            prefix="assignment-filter-expert",
            program=self.program,
        )
        second_submission = self.create_submission(title="Second solution")
        SubmissionExpertAssignment.objects.create(
            submission=second_submission,
            expert=second_expert_user.expert,
            assigned_by=self.manager,
            status=SubmissionExpertAssignment.STATUS_REVOKED,
            revoked_by=self.manager,
            revoked_at=timezone.now(),
            revoke_reason="History",
        )
        self.authenticate()

        response = self.client.get(
            self.list_url,
            {
                "submission_id": self.submission.pk,
                "expert_id": self.expert.pk,
                "status": SubmissionExpertAssignment.STATUS_ASSIGNED,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [matching.pk],
        )

    def test_invalid_filters_get_400(self):
        self.authenticate()

        for query in (
            {"submission_id": "not-a-number"},
            {"expert_id": "not-a-number"},
            {"status": "unknown"},
        ):
            with self.subTest(query=query):
                response = self.client.get(self.list_url, query)
                self.assertEqual(response.status_code, 400)

    def test_response_is_minimal_and_does_not_expose_participant_data(self):
        self.submission.form_data = {"private": "secret"}
        self.submission.save()
        self.create_assignment()
        self.authenticate()

        response = self.client.get(self.list_url)

        item = response.data["results"][0]
        self.assertEqual(
            set(item),
            {
                "id",
                "status",
                "submission",
                "expert",
                "assigned_by_id",
                "assigned_at",
                "completed_at",
                "revoked_by_id",
                "revoked_at",
                "revoke_reason",
                "evaluation_status",
            },
        )
        self.assertEqual(
            set(item["submission"]),
            {"id", "title", "status", "stage_key", "version", "submitted_at"},
        )
        self.assertEqual(
            set(item["expert"]),
            {"id", "user_id", "first_name", "last_name"},
        )
        self.assertNotIn("form_data", item["submission"])
        self.assertNotIn("email", item["expert"])
        self.assertNotIn("participant", item)

    def test_evaluation_status_reports_null_draft_and_submitted(self):
        no_evaluation = self.create_assignment()
        draft_submission = self.create_submission(title="Draft evaluation")
        draft_expert_user = create_rate_expert(
            prefix="assignment-draft-evaluation-expert",
            program=self.program,
        )
        draft_assignment = SubmissionExpertAssignment.objects.create(
            submission=draft_submission,
            expert=draft_expert_user.expert,
            assigned_by=self.manager,
        )
        Evaluation.objects.create(
            submission=draft_submission,
            expert=draft_expert_user.expert,
        )
        submitted_submission = self.create_submission(title="Submitted evaluation")
        submitted_expert_user = create_rate_expert(
            prefix="assignment-submitted-evaluation-expert",
            program=self.program,
        )
        submitted_assignment = SubmissionExpertAssignment.objects.create(
            submission=submitted_submission,
            expert=submitted_expert_user.expert,
            assigned_by=self.manager,
        )
        Evaluation.objects.create(
            submission=submitted_submission,
            expert=submitted_expert_user.expert,
            status=Evaluation.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        self.authenticate()

        response = self.client.get(self.list_url, {"limit": 20})

        statuses = {
            item["id"]: item["evaluation_status"] for item in response.data["results"]
        }
        self.assertIsNone(statuses[no_evaluation.pk])
        self.assertEqual(statuses[draft_assignment.pk], Evaluation.STATUS_DRAFT)
        self.assertEqual(
            statuses[submitted_assignment.pk],
            Evaluation.STATUS_SUBMITTED,
        )


class SubmissionAssignmentCreateAPITests(SubmissionAssignmentTestCase):
    def test_manager_creates_assigned_assignment_with_201(self):
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "assigned")
        self.assertEqual(SubmissionExpertAssignment.objects.count(), 1)

    def test_assigned_by_is_request_user(self):
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["assigned_by_id"], self.manager.pk)
        self.assertEqual(
            SubmissionExpertAssignment.objects.get().assigned_by,
            self.manager,
        )

    def test_repeated_post_returns_same_assignment_with_200(self):
        self.authenticate()

        first = self.client.post(self.list_url, self.create_payload(), format="json")
        second = self.client.post(self.list_url, self.create_payload(), format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["id"], first.data["id"])
        self.assertEqual(SubmissionExpertAssignment.objects.count(), 1)

    def test_repeated_post_preserves_assigned_timestamp_and_actor(self):
        original = self.create_assignment()
        original_assigned_at = original.assigned_at
        self.authenticate(self.staff)

        response = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        original.refresh_from_db()
        self.assertEqual(original.assigned_at, original_assigned_at)
        self.assertEqual(original.assigned_by, self.manager)

    def test_new_episode_is_created_after_revocation(self):
        revoked = self.create_assignment(
            status=SubmissionExpertAssignment.STATUS_REVOKED,
            revoked_by=self.manager,
            revoked_at=timezone.now(),
            revoke_reason="Previous episode",
        )
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data["id"], revoked.pk)
        self.assertEqual(SubmissionExpertAssignment.objects.count(), 2)

    def test_completed_assignment_returns_409(self):
        self.create_assignment(
            status=SubmissionExpertAssignment.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "assignment_completed")

    def test_submission_from_another_program_gets_field_error(self):
        other_submission = self.create_submission(
            program=self.other_program,
            participant=create_user(prefix="wrong-program-participant"),
        )
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(submission_id=other_submission.pk),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("submission_id", response.data)

    def test_expert_from_another_program_gets_field_error(self):
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(expert_id=self.other_expert.pk),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("expert_id", response.data)

    def test_submitted_submission_is_assignable(self):
        self.assertEqual(self.submission.status, Submission.STATUS_SUBMITTED)
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_final_submission_is_assignable(self):
        final_submission = self.create_submission(status=Submission.STATUS_FINAL)
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(submission_id=final_submission.pk),
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_draft_submission_returns_409(self):
        draft = self.create_submission(status=Submission.STATUS_DRAFT)
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(submission_id=draft.pk),
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_returned_submission_returns_409(self):
        returned = self.create_submission(status=Submission.STATUS_RETURNED)
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(submission_id=returned.pk),
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_cancelled_submission_returns_409(self):
        cancelled = self.create_submission(status=Submission.STATUS_CANCELLED)
        self.authenticate()

        response = self.client.post(
            self.list_url,
            self.create_payload(submission_id=cancelled.pk),
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_unknown_ids_get_field_errors(self):
        self.authenticate()

        for payload, field in (
            (self.create_payload(submission_id=999999), "submission_id"),
            (self.create_payload(expert_id=999999), "expert_id"),
        ):
            with self.subTest(field=field):
                response = self.client.post(self.list_url, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

    def test_outsider_cannot_create_assignment(self):
        self.authenticate(self.outsider)

        response = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SubmissionExpertAssignment.objects.exists())

    def test_staff_can_create_assignment(self):
        self.authenticate(self.staff)

        response = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["assigned_by_id"], self.staff.pk)

    def test_invalid_payload_gets_400(self):
        self.authenticate()

        for payload in (
            {},
            {"submission_id": "bad", "expert_id": self.expert.pk},
            {"submission_id": self.submission.pk, "expert_id": "bad"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(self.list_url, payload, format="json")
                self.assertEqual(response.status_code, 400)

    @override_settings(
        REST_FRAMEWORK=throttle_settings(submission_assignment_create="1/min")
    )
    def test_create_is_scoped_throttled(self):
        self.authenticate()
        second_expert = create_rate_expert(
            prefix="assignment-throttle-expert",
            program=self.program,
        ).expert

        first = self.client.post(
            self.list_url,
            self.create_payload(),
            format="json",
            REMOTE_ADDR="203.0.113.80",
        )
        second = self.client.post(
            self.list_url,
            self.create_payload(expert_id=second_expert.pk),
            format="json",
            REMOTE_ADDR="203.0.113.80",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)


class SubmissionAssignmentRevokeAPITests(SubmissionAssignmentTestCase):
    def setUp(self):
        super().setUp()
        self.assignment = self.create_assignment()
        self.revoke_url = f"/submission-assignments/{self.assignment.pk}/revoke/"

    def test_manager_revokes_assigned_assignment(self):
        self.authenticate()

        response = self.client.post(
            self.revoke_url,
            {"reason": "Workload redistribution"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.assignment.status,
            SubmissionExpertAssignment.STATUS_REVOKED,
        )

    def test_revoke_records_actor_timestamp_and_trimmed_reason(self):
        self.authenticate()

        response = self.client.post(
            self.revoke_url,
            {"reason": "  Workload redistribution  "},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.revoked_by, self.manager)
        self.assertIsNotNone(self.assignment.revoked_at)
        self.assertEqual(
            self.assignment.revoke_reason,
            "Workload redistribution",
        )
        self.assertIsNone(self.assignment.completed_at)

    def test_repeated_revoke_is_idempotent(self):
        self.authenticate()

        first = self.client.post(
            self.revoke_url,
            {"reason": "Initial reason"},
            format="json",
        )
        second = self.client.post(
            self.revoke_url,
            {"reason": "Replacement reason"},
            format="json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])

    def test_repeated_revoke_preserves_original_audit_fields(self):
        self.authenticate()
        self.client.post(
            self.revoke_url,
            {"reason": "Initial reason"},
            format="json",
        )
        self.assignment.refresh_from_db()
        original = (
            self.assignment.revoked_at,
            self.assignment.revoked_by_id,
            self.assignment.revoke_reason,
        )

        self.authenticate(self.staff)
        response = self.client.post(
            self.revoke_url,
            {"reason": "Replacement reason"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(
            (
                self.assignment.revoked_at,
                self.assignment.revoked_by_id,
                self.assignment.revoke_reason,
            ),
            original,
        )

    def test_completed_assignment_returns_409(self):
        self.assignment.status = SubmissionExpertAssignment.STATUS_COMPLETED
        self.assignment.completed_at = timezone.now()
        self.assignment.save()
        self.authenticate()

        response = self.client.post(
            self.revoke_url,
            {"reason": "Cannot revoke"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.assignment.status,
            SubmissionExpertAssignment.STATUS_COMPLETED,
        )

    def test_submitted_evaluation_blocks_revoke(self):
        Evaluation.objects.create(
            submission=self.submission,
            expert=self.expert,
            status=Evaluation.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        self.authenticate()

        response = self.client.post(
            self.revoke_url,
            {"reason": "Cannot revoke"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.assignment.status,
            SubmissionExpertAssignment.STATUS_ASSIGNED,
        )

    def test_draft_evaluation_does_not_block_revoke(self):
        Evaluation.objects.create(
            submission=self.submission,
            expert=self.expert,
        )
        self.authenticate()

        response = self.client.post(
            self.revoke_url,
            {"reason": "Reassign"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_draft_evaluation_and_scores_are_preserved(self):
        evaluation = Evaluation.objects.create(
            submission=self.submission,
            expert=self.expert,
        )
        criterion = create_rate_criteria(
            self.program,
            type="float",
        )
        score = EvaluationScore.objects.create(
            evaluation=evaluation,
            criterion=criterion,
            value=Decimal("7.5"),
        )
        self.authenticate()

        response = self.client.post(
            self.revoke_url,
            {"reason": "Reassign"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Evaluation.objects.filter(pk=evaluation.pk).exists())
        self.assertTrue(EvaluationScore.objects.filter(pk=score.pk).exists())
        score.refresh_from_db()
        self.assertEqual(score.value, Decimal("7.500000"))

    def test_other_program_manager_gets_404(self):
        self.authenticate(self.other_manager)

        response = self.client.post(
            self.revoke_url,
            {"reason": "Hidden assignment"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.assignment.status,
            SubmissionExpertAssignment.STATUS_ASSIGNED,
        )

    def test_staff_can_revoke_assignment(self):
        self.authenticate(self.staff)

        response = self.client.post(
            self.revoke_url,
            {"reason": "Staff reassignment"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.revoked_by, self.staff)

    def test_delete_is_not_supported(self):
        self.authenticate()

        response = self.client.delete(self.revoke_url)

        self.assertEqual(response.status_code, 405)
        self.assertTrue(
            SubmissionExpertAssignment.objects.filter(pk=self.assignment.pk).exists()
        )

    def test_reason_is_required_and_nonempty(self):
        self.authenticate()

        for payload in ({}, {"reason": ""}, {"reason": "   "}):
            with self.subTest(payload=payload):
                response = self.client.post(
                    self.revoke_url,
                    payload,
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
        self.assignment.refresh_from_db()
        self.assertEqual(
            self.assignment.status,
            SubmissionExpertAssignment.STATUS_ASSIGNED,
        )


class SubmissionAssignmentServiceRaceTests(SubmissionAssignmentTestCase):
    def test_integrity_error_race_returns_existing_assigned_episode(self):
        existing = self.create_assignment()
        real_get_active_assignment = submission_assignment_service._get_active_assignment
        lookup_count = 0

        def simulate_race_lookup(**kwargs):
            nonlocal lookup_count
            lookup_count += 1
            if lookup_count == 1:
                return None
            return real_get_active_assignment(**kwargs)

        with patch(
            "partner_programs.services.submission_assignments." "_get_active_assignment",
            side_effect=simulate_race_lookup,
        ), patch.object(
            SubmissionExpertAssignment,
            "full_clean",
            return_value=None,
        ):
            result = create_submission_assignment(
                program=self.program,
                submission_id=self.submission.pk,
                expert_id=self.expert.pk,
                actor=self.manager,
            )

        self.assertFalse(result.created)
        self.assertEqual(result.assignment, existing)
        self.assertEqual(lookup_count, 2)
        self.assertEqual(
            SubmissionExpertAssignment.objects.get(pk=existing.pk),
            existing,
        )
        self.assertFalse(transaction.get_connection().needs_rollback)

    def test_integrity_error_race_with_completed_episode_is_conflict(self):
        existing = self.create_assignment(
            status=SubmissionExpertAssignment.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        real_get_active_assignment = submission_assignment_service._get_active_assignment
        lookup_count = 0

        def simulate_race_lookup(**kwargs):
            nonlocal lookup_count
            lookup_count += 1
            if lookup_count == 1:
                return None
            return real_get_active_assignment(**kwargs)

        with patch(
            "partner_programs.services.submission_assignments." "_get_active_assignment",
            side_effect=simulate_race_lookup,
        ), patch.object(
            SubmissionExpertAssignment,
            "full_clean",
            return_value=None,
        ):
            with self.assertRaises(AssignmentCompletedError):
                create_submission_assignment(
                    program=self.program,
                    submission_id=self.submission.pk,
                    expert_id=self.expert.pk,
                    actor=self.manager,
                )

        self.assertEqual(lookup_count, 2)
        self.assertEqual(
            SubmissionExpertAssignment.objects.get(pk=existing.pk),
            existing,
        )
        self.assertFalse(transaction.get_connection().needs_rollback)


class SubmissionAssignmentURLContractTests(SimpleTestCase):
    def test_reverse_builds_exact_assignment_urls(self):
        self.assertEqual(
            reverse(
                "partner_programs:submission-assignment-list-create",
                kwargs={"program_id": 17},
            ),
            "/programs/17/submission-assignments/",
        )
        self.assertEqual(
            reverse(
                "submission-assignment-revoke",
                kwargs={"assignment_id": 23},
            ),
            "/submission-assignments/23/revoke/",
        )

    def test_incorrect_prefixed_assignment_urls_do_not_resolve(self):
        for url in (
            "/programs/programs/17/submission-assignments/",
            "/programs/submission-assignments/23/revoke/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(Resolver404):
                    resolve(url)
