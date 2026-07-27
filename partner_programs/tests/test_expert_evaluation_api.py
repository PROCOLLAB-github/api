# Roadmap: DEV-050, DEV-051, DEV-052
# Проверки экспертного доступа, autosave, submit и manager read-only API.

from decimal import Decimal
from threading import Barrier, Thread

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    Evaluation,
    EvaluationScore,
    Submission,
    SubmissionExpertAssignment,
)
from partner_programs.services.evaluations import submit_evaluation
from partner_programs.tests.helpers import create_partner_program, create_user
from project_rates.tests.helpers import create_rate_criteria, create_rate_expert


def throttle_settings(**rates):
    rest_framework = dict(settings.REST_FRAMEWORK)
    rest_framework["DEFAULT_THROTTLE_RATES"] = {
        **rest_framework.get("DEFAULT_THROTTLE_RATES", {}),
        **rates,
    }
    return rest_framework


class ExpertEvaluationAPITestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.manager = create_user(prefix="evaluation-api-manager")
        self.other_manager = create_user(prefix="evaluation-api-other-manager")
        self.staff = create_user(prefix="evaluation-api-staff", is_staff=True)
        self.participant = create_user(prefix="evaluation-api-participant")
        self.program = create_partner_program()
        self.other_program = create_partner_program()
        self.program.managers.add(self.manager)
        self.other_program.managers.add(self.other_manager)
        self.expert_user = create_rate_expert(
            prefix="evaluation-api-expert",
            program=self.program,
        )
        self.expert = self.expert_user.expert
        self.other_expert_user = create_rate_expert(
            prefix="evaluation-api-other-expert",
            program=self.program,
        )
        self.other_expert = self.other_expert_user.expert
        self.foreign_expert_user = create_rate_expert(
            prefix="evaluation-api-foreign-expert",
            program=self.other_program,
        )
        self.foreign_expert = self.foreign_expert_user.expert
        self.submission = self.create_submission(participant=self.participant)
        self.assignment = self.create_assignment()
        self.int_criterion = create_rate_criteria(
            self.program,
            name="Impact",
            type="int",
            min_value=1,
            max_value=10,
        )
        self.float_criterion = create_rate_criteria(
            self.program,
            name="Feasibility",
            type="float",
            min_value=0.5,
            max_value=5.5,
        )

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.expert_user)

    def create_submission(
        self,
        *,
        program=None,
        participant=None,
        status=Submission.STATUS_SUBMITTED,
        title="Expert solution",
        form_data=None,
        links=None,
    ):
        program = program or self.program
        participant = participant or create_user(
            prefix="evaluation-submission-participant"
        )
        application = Application.objects.create(
            program=program,
            user=participant,
            created_by=participant,
            status=Application.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
            form_data={"registration_secret": "private"},
        )
        return Submission.objects.create(
            application=application,
            program=program,
            submitted_by=participant,
            title=title,
            description="Solution description",
            form_data=form_data or {"solution_secret": "private"},
            links=links or ["https://example.com/solution"],
            status=status,
            submitted_at=(
                timezone.now()
                if status in (Submission.STATUS_SUBMITTED, Submission.STATUS_FINAL)
                else None
            ),
        )

    def create_assignment(self, *, submission=None, expert=None, **overrides):
        values = {
            "submission": submission or self.submission,
            "expert": expert or self.expert,
            "assigned_by": self.manager,
        }
        values.update(overrides)
        return SubmissionExpertAssignment.objects.create(**values)

    def create_evaluation(self, *, submission=None, expert=None, **overrides):
        values = {
            "submission": submission or self.submission,
            "expert": expert or self.expert,
        }
        values.update(overrides)
        return Evaluation.objects.create(**values)

    def score_payload(self, *, int_value="8", float_value="4.5"):
        return [
            {"criterion_id": self.int_criterion.pk, "value": int_value},
            {"criterion_id": self.float_criterion.pk, "value": float_value},
        ]


class ExpertSubmissionAPITests(ExpertEvaluationAPITestCase):
    def test_list_contains_only_current_expert_assignments(self):
        other_submission = self.create_submission(title="Other expert solution")
        self.create_assignment(
            submission=other_submission,
            expert=self.other_expert,
        )
        self.authenticate()

        response = self.client.get("/expert/submissions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.submission.pk)

    def test_completed_assignment_remains_visible(self):
        self.assignment.status = SubmissionExpertAssignment.STATUS_COMPLETED
        self.assignment.completed_at = timezone.now()
        self.assignment.save()
        self.authenticate()

        response = self.client.get("/expert/submissions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["assignment"]["status"],
            SubmissionExpertAssignment.STATUS_COMPLETED,
        )

    def test_unassigned_and_foreign_submissions_are_hidden(self):
        self.create_submission(title="Unassigned")
        foreign_submission = self.create_submission(
            program=self.other_program,
            title="Foreign",
        )
        self.create_assignment(
            submission=foreign_submission,
            expert=self.foreign_expert,
            assigned_by=self.other_manager,
        )
        self.authenticate()

        response = self.client.get("/expert/submissions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_manager_and_participant_cannot_use_expert_list(self):
        for user in (self.manager, self.participant):
            with self.subTest(user=user.pk):
                self.authenticate(user)
                response = self.client.get("/expert/submissions/")
                self.assertEqual(response.status_code, 403)

    def test_list_filters_program_submission_and_evaluation_status(self):
        evaluation = self.create_evaluation()
        other_submission = self.create_submission(status=Submission.STATUS_FINAL)
        self.create_assignment(submission=other_submission)
        self.authenticate()

        response = self.client.get(
            "/expert/submissions/",
            {
                "program_id": self.program.pk,
                "submission_status": Submission.STATUS_SUBMITTED,
                "evaluation_status": Evaluation.STATUS_DRAFT,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [evaluation.submission_id],
        )

    def test_list_supports_limit_offset_pagination(self):
        for index in range(11):
            submission = self.create_submission(title=f"Solution {index}")
            self.create_assignment(submission=submission)
        self.authenticate()

        first = self.client.get("/expert/submissions/")
        second = self.client.get("/expert/submissions/", {"offset": 10})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["count"], 12)
        self.assertEqual(len(first.data["results"]), 10)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.data["results"]), 2)

    def test_detail_returns_safe_solution_fields_and_numeric_criteria(self):
        create_rate_criteria(self.program, name="Comment", type="str")
        self.authenticate()

        response = self.client.get(f"/expert/submissions/{self.submission.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["description"], "Solution description")
        self.assertEqual(response.data["links"], ["https://example.com/solution"])
        self.assertEqual(
            {item["id"] for item in response.data["criteria"]},
            {self.int_criterion.pk, self.float_criterion.pk},
        )

    def test_detail_does_not_expose_participant_pii_or_form_data(self):
        self.authenticate()

        response = self.client.get(f"/expert/submissions/{self.submission.pk}/")

        self.assertEqual(response.status_code, 200)
        forbidden = {
            "application",
            "form_data",
            "submitted_by",
            "user",
            "created_by",
            "email",
            "phone",
            "team",
            "team_members",
        }
        self.assertFalse(forbidden.intersection(response.data))
        self.assertNotIn("registration_secret", str(response.data))
        self.assertNotIn("solution_secret", str(response.data))
        self.assertNotIn(self.participant.email, str(response.data))

    def test_unassigned_expert_gets_404_for_detail(self):
        self.authenticate(self.other_expert_user)

        response = self.client.get(f"/expert/submissions/{self.submission.pk}/")

        self.assertEqual(response.status_code, 404)

    def test_assignment_without_program_membership_does_not_grant_access(self):
        self.create_assignment(expert=self.foreign_expert)
        evaluation = self.create_evaluation(expert=self.foreign_expert)
        self.authenticate(self.foreign_expert_user)

        list_response = self.client.get("/expert/submissions/")
        detail_response = self.client.get(f"/expert/submissions/{self.submission.pk}/")
        evaluation_response = self.client.get(f"/evaluations/{evaluation.pk}/")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 0)
        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(evaluation_response.status_code, 404)

    def test_detail_does_not_expose_other_experts_evaluation(self):
        self.create_assignment(expert=self.other_expert)
        other_evaluation = self.create_evaluation(expert=self.other_expert)
        other_evaluation.comment = "Private expert comment"
        other_evaluation.save()
        self.authenticate()

        response = self.client.get(f"/expert/submissions/{self.submission.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["my_evaluation"])
        self.assertNotIn("Private expert comment", str(response.data))

    def test_staff_can_open_expert_submission_detail(self):
        self.authenticate(self.staff)

        response = self.client.get(f"/expert/submissions/{self.submission.pk}/")

        self.assertEqual(response.status_code, 200)


class EvaluationDraftCreateAPITests(ExpertEvaluationAPITestCase):
    @property
    def create_url(self):
        return f"/submissions/{self.submission.pk}/evaluations/"

    def test_create_empty_draft(self):
        self.authenticate()

        response = self.client.post(self.create_url, {}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], Evaluation.STATUS_DRAFT)
        self.assertEqual(response.data["comment"], "")
        self.assertEqual(response.data["scores"], [])

    def test_create_draft_with_scores(self):
        self.authenticate()

        response = self.client.post(
            self.create_url,
            {"comment": "Strong", "scores": self.score_payload()},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["comment"], "Strong")
        self.assertEqual(len(response.data["scores"]), 2)

    def test_repeated_post_returns_existing_without_changes(self):
        self.authenticate()
        first = self.client.post(
            self.create_url,
            {"comment": "Original", "scores": self.score_payload()},
            format="json",
        )

        second = self.client.post(
            self.create_url,
            {"comment": "Replacement", "scores": []},
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["id"], first.data["id"])
        self.assertEqual(second.data["comment"], "Original")
        self.assertEqual(len(second.data["scores"]), 2)

    def test_existing_submitted_evaluation_returns_409(self):
        self.create_evaluation(
            status=Evaluation.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        self.authenticate()

        response = self.client.post(self.create_url, {}, format="json")

        self.assertEqual(response.status_code, 409)

    def test_missing_assignment_returns_404(self):
        submission = self.create_submission()
        self.authenticate()

        response = self.client.post(
            f"/submissions/{submission.pk}/evaluations/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_revoked_assignment_returns_409(self):
        self.assignment.status = SubmissionExpertAssignment.STATUS_REVOKED
        self.assignment.revoked_by = self.manager
        self.assignment.revoked_at = timezone.now()
        self.assignment.revoke_reason = "Reassigned"
        self.assignment.save()
        self.authenticate()

        response = self.client.post(self.create_url, {}, format="json")

        self.assertEqual(response.status_code, 409)

    def test_invalid_submission_status_returns_409(self):
        for submission_status in (
            Submission.STATUS_DRAFT,
            Submission.STATUS_RETURNED,
            Submission.STATUS_CANCELLED,
        ):
            with self.subTest(status=submission_status):
                submission = self.create_submission(status=submission_status)
                self.create_assignment(submission=submission)
                self.authenticate()
                response = self.client.post(
                    f"/submissions/{submission.pk}/evaluations/",
                    {},
                    format="json",
                )
                self.assertEqual(response.status_code, 409)

    def test_criterion_from_another_program_returns_400(self):
        criterion = create_rate_criteria(self.other_program, type="int")
        self.authenticate()

        response = self.client.post(
            self.create_url,
            {"scores": [{"criterion_id": criterion.pk, "value": "5"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_non_numeric_criterion_returns_400(self):
        criterion = create_rate_criteria(self.program, type="str")
        self.authenticate()

        response = self.client.post(
            self.create_url,
            {"scores": [{"criterion_id": criterion.pk, "value": "5"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_fractional_int_and_out_of_range_values_return_400(self):
        self.authenticate()
        payloads = (
            {"scores": [{"criterion_id": self.int_criterion.pk, "value": "7.5"}]},
            {"scores": [{"criterion_id": self.int_criterion.pk, "value": "11"}]},
            {"scores": [{"criterion_id": self.float_criterion.pk, "value": "0.4"}]},
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    self.create_url,
                    payload,
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(Evaluation.objects.exists())

    def test_duplicate_criteria_return_400(self):
        self.authenticate()

        response = self.client.post(
            self.create_url,
            {
                "scores": [
                    {"criterion_id": self.int_criterion.pk, "value": "7"},
                    {"criterion_id": self.int_criterion.pk, "value": "8"},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_my_evaluation_get_does_not_create(self):
        self.authenticate()

        response = self.client.get(f"/submissions/{self.submission.pk}/evaluations/my/")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Evaluation.objects.exists())

    def test_my_evaluation_get_returns_own_scores(self):
        evaluation = self.create_evaluation()
        EvaluationScore.objects.create(
            evaluation=evaluation,
            criterion=self.int_criterion,
            value=Decimal("8"),
        )
        self.authenticate()

        response = self.client.get(f"/submissions/{self.submission.pk}/evaluations/my/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], evaluation.pk)
        self.assertEqual(len(response.data["scores"]), 1)

    @override_settings(REST_FRAMEWORK=throttle_settings(evaluation_create="1/min"))
    def test_create_is_scoped_throttled(self):
        self.authenticate()

        first = self.client.post(
            self.create_url,
            {},
            format="json",
            REMOTE_ADDR="203.0.113.90",
        )
        second = self.client.post(
            self.create_url,
            {},
            format="json",
            REMOTE_ADDR="203.0.113.90",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)


class EvaluationPatchAPITests(ExpertEvaluationAPITestCase):
    def setUp(self):
        super().setUp()
        self.evaluation = self.create_evaluation(comment="Initial")
        self.url = f"/evaluations/{self.evaluation.pk}/"

    def test_owner_updates_comment(self):
        self.authenticate()

        response = self.client.patch(
            self.url,
            {"comment": "Updated"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.comment, "Updated")

    def test_scores_are_replaced_as_complete_set(self):
        EvaluationScore.objects.create(
            evaluation=self.evaluation,
            criterion=self.int_criterion,
            value=Decimal("5"),
        )
        self.authenticate()

        response = self.client.patch(
            self.url,
            {"scores": [{"criterion_id": self.float_criterion.pk, "value": "4.25"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(self.evaluation.scores.values_list("criterion_id", flat=True)),
            {self.float_criterion.pk},
        )

    def test_empty_scores_removes_all_scores(self):
        EvaluationScore.objects.create(
            evaluation=self.evaluation,
            criterion=self.int_criterion,
            value=Decimal("5"),
        )
        self.authenticate()

        response = self.client.patch(self.url, {"scores": []}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.evaluation.scores.exists())

    def test_invalid_score_rolls_back_comment_and_scores(self):
        original = EvaluationScore.objects.create(
            evaluation=self.evaluation,
            criterion=self.int_criterion,
            value=Decimal("5"),
        )
        foreign = create_rate_criteria(self.other_program, type="int")
        self.authenticate()

        response = self.client.patch(
            self.url,
            {
                "comment": "Must rollback",
                "scores": [
                    {"criterion_id": self.float_criterion.pk, "value": "4"},
                    {"criterion_id": foreign.pk, "value": "3"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.comment, "Initial")
        self.assertEqual(
            list(self.evaluation.scores.values_list("id", flat=True)),
            [original.pk],
        )

    def test_other_expert_and_manager_cannot_patch(self):
        for user in (self.other_expert_user, self.manager):
            with self.subTest(user=user.pk):
                self.authenticate(user)
                response = self.client.patch(
                    self.url,
                    {"comment": "Forbidden"},
                    format="json",
                )
                self.assertEqual(response.status_code, 404)

    def test_revoked_assignment_returns_409(self):
        self.assignment.status = SubmissionExpertAssignment.STATUS_REVOKED
        self.assignment.revoked_by = self.manager
        self.assignment.revoked_at = timezone.now()
        self.assignment.revoke_reason = "Reassigned"
        self.assignment.save()
        self.authenticate()

        response = self.client.patch(
            self.url,
            {"comment": "Forbidden"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_submitted_evaluation_returns_409(self):
        self.evaluation.status = Evaluation.STATUS_SUBMITTED
        self.evaluation.submitted_at = timezone.now()
        self.evaluation.save()
        self.authenticate()

        response = self.client.patch(
            self.url,
            {"comment": "Forbidden"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_identical_patch_is_safe(self):
        self.authenticate()
        payload = {"comment": "Initial", "scores": self.score_payload()}

        first = self.client.patch(self.url, payload, format="json")
        second = self.client.patch(self.url, payload, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.evaluation.scores.count(), 2)

    @override_settings(REST_FRAMEWORK=throttle_settings(evaluation_update="1/min"))
    def test_patch_is_scoped_throttled(self):
        self.authenticate()

        first = self.client.patch(
            self.url,
            {"comment": "First"},
            format="json",
            REMOTE_ADDR="203.0.113.91",
        )
        second = self.client.patch(
            self.url,
            {"comment": "Second"},
            format="json",
            REMOTE_ADDR="203.0.113.91",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


class EvaluationSubmitAPITests(ExpertEvaluationAPITestCase):
    def setUp(self):
        super().setUp()
        self.evaluation = self.create_evaluation(comment="Ready")
        for criterion, value in (
            (self.int_criterion, Decimal("8")),
            (self.float_criterion, Decimal("4.5")),
        ):
            EvaluationScore.objects.create(
                evaluation=self.evaluation,
                criterion=criterion,
                value=value,
            )
        self.url = f"/evaluations/{self.evaluation.pk}/submit/"

    def test_submit_completes_evaluation_and_assignment(self):
        self.authenticate()

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.evaluation.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(self.evaluation.status, Evaluation.STATUS_SUBMITTED)
        self.assertIsNotNone(self.evaluation.submitted_at)
        self.assertIsNone(self.evaluation.total_score)
        self.assertEqual(
            self.assignment.status,
            SubmissionExpertAssignment.STATUS_COMPLETED,
        )
        self.assertIsNotNone(self.assignment.completed_at)
        self.assertEqual(
            self.assignment.completed_at,
            self.evaluation.submitted_at,
        )

    def test_incomplete_criteria_return_400(self):
        self.evaluation.scores.filter(criterion=self.float_criterion).delete()
        self.authenticate()

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.evaluation.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(self.evaluation.status, Evaluation.STATUS_DRAFT)
        self.assertEqual(
            self.assignment.status,
            SubmissionExpertAssignment.STATUS_ASSIGNED,
        )

    def test_changed_range_is_revalidated_on_submit(self):
        self.int_criterion.max_value = 5
        self.int_criterion.save()
        self.authenticate()

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_wrong_submission_status_returns_409(self):
        self.submission.status = Submission.STATUS_RETURNED
        self.submission.submitted_at = None
        self.submission.save()
        self.authenticate()

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 409)

    def test_repeated_submit_is_idempotent_and_preserves_timestamp(self):
        self.authenticate()
        first = self.client.post(self.url, {}, format="json")
        self.evaluation.refresh_from_db()
        submitted_at = self.evaluation.submitted_at

        second = self.client.post(self.url, {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.submitted_at, submitted_at)

    def test_other_expert_cannot_submit(self):
        self.authenticate(self.other_expert_user)

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 404)

    @override_settings(REST_FRAMEWORK=throttle_settings(evaluation_submit="1/min"))
    def test_submit_is_scoped_throttled(self):
        self.authenticate()

        first = self.client.post(
            self.url,
            {},
            format="json",
            REMOTE_ADDR="203.0.113.92",
        )
        second = self.client.post(
            self.url,
            {},
            format="json",
            REMOTE_ADDR="203.0.113.92",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


class EvaluationReadAndManagerAPITests(ExpertEvaluationAPITestCase):
    def setUp(self):
        super().setUp()
        self.evaluation = self.create_evaluation(comment="Manager-visible")
        EvaluationScore.objects.create(
            evaluation=self.evaluation,
            criterion=self.int_criterion,
            value=Decimal("7"),
        )
        self.detail_url = f"/evaluations/{self.evaluation.pk}/"
        self.manager_list_url = f"/programs/{self.program.pk}/evaluations/"
        self.manager_detail_url = (
            f"/programs/{self.program.pk}/evaluations/{self.evaluation.pk}/"
        )

    def test_owner_manager_and_staff_can_read_evaluation(self):
        for user in (self.expert_user, self.manager, self.staff):
            with self.subTest(user=user.pk):
                self.authenticate(user)
                response = self.client.get(self.detail_url)
                self.assertEqual(response.status_code, 200)

    def test_other_expert_and_participant_cannot_read_evaluation(self):
        for user in (self.other_expert_user, self.participant):
            with self.subTest(user=user.pk):
                self.authenticate(user)
                response = self.client.get(self.detail_url)
                self.assertEqual(response.status_code, 404)

    def test_manager_sees_own_program_evaluations_and_scores(self):
        self.authenticate(self.manager)

        response = self.client.get(self.manager_list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        item = response.data["results"][0]
        self.assertEqual(item["id"], self.evaluation.pk)
        self.assertEqual(item["comment"], "Manager-visible")
        self.assertEqual(len(item["scores"]), 1)
        self.assertEqual(item["assignment"]["id"], self.assignment.pk)

    def test_other_manager_and_participant_cannot_use_manager_list(self):
        for user in (self.other_manager, self.participant):
            with self.subTest(user=user.pk):
                self.authenticate(user)
                response = self.client.get(self.manager_list_url)
                self.assertEqual(response.status_code, 403)

    def test_staff_can_use_manager_list(self):
        self.authenticate(self.staff)

        response = self.client.get(self.manager_list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_manager_filters_work(self):
        self.authenticate(self.manager)

        response = self.client.get(
            self.manager_list_url,
            {
                "submission_id": self.submission.pk,
                "expert_id": self.expert.pk,
                "evaluation_status": Evaluation.STATUS_DRAFT,
                "assignment_status": SubmissionExpertAssignment.STATUS_ASSIGNED,
                "stage_key": "main",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_manager_detail_is_scoped_to_program(self):
        self.authenticate(self.manager)
        own = self.client.get(self.manager_detail_url)

        self.authenticate(self.other_manager)
        hidden = self.client.get(self.manager_detail_url)

        self.assertEqual(own.status_code, 200)
        self.assertEqual(hidden.status_code, 403)

    def test_manager_api_is_read_only(self):
        self.authenticate(self.manager)

        for method in ("post", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.manager_detail_url,
                    {"comment": "Forbidden", "scores": []},
                    format="json",
                )
                self.assertEqual(response.status_code, 405)
        self.evaluation.refresh_from_db()
        self.assertEqual(self.evaluation.comment, "Manager-visible")

    def test_assignment_list_contains_evaluation_summary_without_pii(self):
        self.authenticate(self.manager)

        response = self.client.get(f"/programs/{self.program.pk}/submission-assignments/")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(item["evaluation"]["id"], self.evaluation.pk)
        self.assertEqual(
            item["evaluation"]["status"],
            Evaluation.STATUS_DRAFT,
        )
        self.assertNotIn("form_data", str(item))


class ConcurrentEvaluationSubmitTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.manager = create_user(prefix="concurrent-evaluation-manager")
        self.participant = create_user(prefix="concurrent-evaluation-participant")
        self.program = create_partner_program()
        application = Application.objects.create(
            program=self.program,
            user=self.participant,
            created_by=self.participant,
            status=Application.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        self.submission = Submission.objects.create(
            application=application,
            program=self.program,
            submitted_by=self.participant,
            title="Concurrent solution",
            status=Submission.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        self.expert_user = create_rate_expert(
            prefix="concurrent-evaluation-expert",
            program=self.program,
        )
        self.assignment = SubmissionExpertAssignment.objects.create(
            submission=self.submission,
            expert=self.expert_user.expert,
            assigned_by=self.manager,
        )
        criterion = create_rate_criteria(
            self.program,
            type="int",
            min_value=1,
            max_value=10,
        )
        self.evaluation = Evaluation.objects.create(
            submission=self.submission,
            expert=self.expert_user.expert,
        )
        EvaluationScore.objects.create(
            evaluation=self.evaluation,
            criterion=criterion,
            value=Decimal("8"),
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_submit_keeps_consistent_terminal_state(self):
        barrier = Barrier(2)
        results = []
        errors = []

        def worker():
            close_old_connections()
            try:
                user = type(self.expert_user).objects.get(pk=self.expert_user.pk)
                barrier.wait()
                evaluation = submit_evaluation(
                    evaluation_id=self.evaluation.pk,
                    user=user,
                )
                results.append(evaluation.status)
            except Exception as exc:  # pragma: no cover - диагностируется результатом
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [Thread(target=worker), Thread(target=worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(errors)
        self.assertEqual(results, [Evaluation.STATUS_SUBMITTED] * 2)
        self.evaluation.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(self.evaluation.status, Evaluation.STATUS_SUBMITTED)
        self.assertEqual(
            self.assignment.status,
            SubmissionExpertAssignment.STATUS_COMPLETED,
        )
        self.assertEqual(
            self.evaluation.submitted_at,
            self.assignment.completed_at,
        )
