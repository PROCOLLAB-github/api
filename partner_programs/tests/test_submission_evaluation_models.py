from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from partner_programs.models import (
    Application,
    Evaluation,
    EvaluationScore,
    Submission,
    SubmissionExpertAssignment,
)
from partner_programs.tests.helpers import create_partner_program, create_user
from project_rates.tests.helpers import create_rate_criteria, create_rate_expert


class SubmissionEvaluationModelTestCase(TestCase):
    def setUp(self):
        self.user = create_user(prefix="evaluation-participant")
        self.manager = create_user(prefix="evaluation-manager")
        self.program = create_partner_program()
        self.application = Application.objects.create(
            program=self.program,
            user=self.user,
            created_by=self.user,
        )
        self.submission = Submission.objects.create(
            application=self.application,
            program=self.program,
            submitted_by=self.user,
            title="Evaluation solution",
        )
        self.expert_user = create_rate_expert(
            prefix="submission-expert",
            program=self.program,
        )
        self.expert = self.expert_user.expert


class SubmissionExpertAssignmentModelTests(SubmissionEvaluationModelTestCase):
    def create_assignment(self, **overrides):
        values = {
            "submission": self.submission,
            "expert": self.expert,
            "assigned_by": self.manager,
        }
        values.update(overrides)
        return SubmissionExpertAssignment.objects.create(**values)

    def test_can_create_assigned_assignment_with_defaults(self):
        assignment = self.create_assignment()

        self.assertEqual(
            assignment.status,
            SubmissionExpertAssignment.STATUS_ASSIGNED,
        )
        self.assertIsNotNone(assignment.assigned_at)
        self.assertIsNotNone(assignment.created_at)
        self.assertIsNotNone(assignment.updated_at)
        self.assertIsNone(assignment.completed_at)
        self.assertIsNone(assignment.revoked_at)
        self.assertIsNone(assignment.revoked_by)
        self.assertEqual(assignment.revoke_reason, "")

    def test_duplicate_assigned_assignment_is_rejected(self):
        self.create_assignment()

        with self.assertRaises(ValidationError):
            self.create_assignment()

    def test_assigned_assignment_is_rejected_after_completed_assignment(self):
        self.create_assignment(
            status=SubmissionExpertAssignment.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )

        with self.assertRaises(ValidationError):
            self.create_assignment()

    def test_multiple_revoked_assignments_are_allowed(self):
        for reason in ("Переназначение", "Изменение состава экспертов"):
            self.create_assignment(
                status=SubmissionExpertAssignment.STATUS_REVOKED,
                revoked_by=self.manager,
                revoked_at=timezone.now(),
                revoke_reason=reason,
            )

        self.assertEqual(
            SubmissionExpertAssignment.objects.filter(
                submission=self.submission,
                expert=self.expert,
            ).count(),
            2,
        )

    def test_completed_assignment_requires_completed_at(self):
        with self.assertRaises(ValidationError):
            self.create_assignment(
                status=SubmissionExpertAssignment.STATUS_COMPLETED,
            )

    def test_revoked_assignment_requires_revoked_at(self):
        with self.assertRaises(ValidationError):
            self.create_assignment(
                status=SubmissionExpertAssignment.STATUS_REVOKED,
                revoked_by=self.manager,
            )

    def test_assigned_assignment_rejects_lifecycle_timestamps(self):
        for field in ("completed_at", "revoked_at"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.create_assignment(**{field: timezone.now()})


class EvaluationModelTests(SubmissionEvaluationModelTestCase):
    def create_evaluation(self, **overrides):
        values = {
            "submission": self.submission,
            "expert": self.expert,
        }
        values.update(overrides)
        return Evaluation.objects.create(**values)

    def test_can_create_draft_evaluation(self):
        evaluation = self.create_evaluation()

        self.assertEqual(evaluation.status, Evaluation.STATUS_DRAFT)
        self.assertEqual(evaluation.comment, "")
        self.assertIsNone(evaluation.total_score)
        self.assertIsNone(evaluation.submitted_at)

    def test_submission_and_expert_are_unique(self):
        self.create_evaluation()

        with self.assertRaises(ValidationError):
            self.create_evaluation()

    def test_draft_evaluation_rejects_submitted_at(self):
        with self.assertRaises(ValidationError):
            self.create_evaluation(submitted_at=timezone.now())

    def test_submitted_evaluation_requires_submitted_at(self):
        with self.assertRaises(ValidationError):
            self.create_evaluation(status=Evaluation.STATUS_SUBMITTED)

    def test_submitted_evaluation_with_submitted_at_is_allowed(self):
        submitted_at = timezone.now()

        evaluation = self.create_evaluation(
            status=Evaluation.STATUS_SUBMITTED,
            submitted_at=submitted_at,
        )

        self.assertEqual(evaluation.submitted_at, submitted_at)


class EvaluationScoreModelTests(SubmissionEvaluationModelTestCase):
    def setUp(self):
        super().setUp()
        self.evaluation = Evaluation.objects.create(
            submission=self.submission,
            expert=self.expert,
        )
        self.criterion = create_rate_criteria(
            self.program,
            name="Impact",
            type="float",
            min_value=0.5,
            max_value=10.5,
        )

    def create_score(self, **overrides):
        values = {
            "evaluation": self.evaluation,
            "criterion": self.criterion,
            "value": Decimal("7.250000"),
        }
        values.update(overrides)
        return EvaluationScore.objects.create(**values)

    def test_can_create_numeric_evaluation_score_with_decimal_value(self):
        score = self.create_score()

        self.assertEqual(score.value, Decimal("7.250000"))
        self.assertIsInstance(score.value, Decimal)

    def test_evaluation_and_criterion_are_unique(self):
        self.create_score()

        with self.assertRaises(ValidationError):
            self.create_score(value=Decimal("8.000000"))

    def test_used_criterion_is_protected(self):
        self.create_score()

        with self.assertRaises(ProtectedError):
            self.criterion.delete()

    def test_criterion_snapshot_is_captured(self):
        score = self.create_score()

        self.assertEqual(score.criterion_name, self.criterion.name)
        self.assertEqual(score.criterion_type, "float")
        self.assertEqual(score.min_value, 0.5)
        self.assertEqual(score.max_value, 10.5)

    def test_criterion_changes_do_not_change_snapshot(self):
        score = self.create_score()
        original_snapshot = (
            score.criterion_name,
            score.criterion_type,
            score.min_value,
            score.max_value,
        )
        self.criterion.name = "Updated impact"
        self.criterion.type = "int"
        self.criterion.min_value = 1
        self.criterion.max_value = 20
        self.criterion.save()

        score.refresh_from_db()

        self.assertEqual(
            (
                score.criterion_name,
                score.criterion_type,
                score.min_value,
                score.max_value,
            ),
            original_snapshot,
        )

    def test_non_numeric_criterion_is_rejected(self):
        criterion = create_rate_criteria(
            self.program,
            name="Comment",
            type="str",
        )

        with self.assertRaises(ValidationError) as error:
            self.create_score(criterion=criterion)

        self.assertIn("criterion", error.exception.message_dict)
