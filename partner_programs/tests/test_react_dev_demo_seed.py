# Roadmap: DEV-072
# Безопасность, повторяемость и API-контракт демонстрационного React-dev набора.

import io
import os
import secrets
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import include, path
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    Evaluation,
    EvaluationScore,
    PartnerProgram,
    PartnerProgramUserProfile,
    Submission,
    SubmissionExpertAssignment,
    Team,
    TeamMember,
)
from partner_programs.services.react_dev_demo import (
    DEMO_CRITERION_SPECS,
    DEMO_PROGRAM_NAME,
    DEMO_PROGRAM_TAG,
    DEMO_SUBMISSION_SPECS,
    DEMO_USER_SPECS,
)
from partner_programs.tests.helpers import create_partner_program, create_user
from project_rates.models import Criteria
from users.models import CustomUser

urlpatterns = [
    path("expert/", include("partner_programs.expert_urls")),
]


@override_settings(ROOT_URLCONF=__name__)
class ReactDevDemoSeedTests(TestCase):
    def setUp(self):
        self.demo_password = secrets.token_urlsafe(32)

    def run_seed(self, *extra_args, confirm=True, password=True):
        args = list(extra_args)
        if confirm:
            args.append("--confirm-react-dev")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with override_settings(ALLOW_REACT_DEV_DEMO_SEED=True):
            with patch.dict(os.environ, {}, clear=False):
                if password:
                    os.environ["REACT_DEV_DEMO_PASSWORD"] = self.demo_password
                else:
                    os.environ.pop("REACT_DEV_DEMO_PASSWORD", None)
                call_command(
                    "seed_react_dev_demo",
                    *args,
                    stdout=stdout,
                    stderr=stderr,
                )
        return stdout.getvalue(), stderr.getvalue()

    def assert_demo_absent(self):
        self.assertFalse(
            PartnerProgram.objects.filter(
                name=DEMO_PROGRAM_NAME,
                tag=DEMO_PROGRAM_TAG,
            ).exists()
        )
        self.assertFalse(
            CustomUser.objects.filter(
                email__in=[spec["email"] for spec in DEMO_USER_SPECS]
            ).exists()
        )

    def test_seed_is_disabled_by_default_before_any_write(self):
        with patch.dict(
            os.environ,
            {"REACT_DEV_DEMO_PASSWORD": self.demo_password},
        ):
            with self.assertRaisesMessage(CommandError, "отключено"):
                call_command(
                    "seed_react_dev_demo",
                    "--confirm-react-dev",
                )

        self.assert_demo_absent()

    def test_seed_requires_explicit_react_dev_confirmation_before_any_write(self):
        with self.assertRaisesMessage(CommandError, "--confirm-react-dev"):
            self.run_seed(confirm=False)

        self.assert_demo_absent()

    def test_seed_requires_password_environment_variable_before_any_write(self):
        with self.assertRaisesMessage(CommandError, "REACT_DEV_DEMO_PASSWORD"):
            self.run_seed(password=False)

        self.assert_demo_absent()

    def test_first_run_creates_the_complete_linked_dataset(self):
        self.run_seed()

        program = PartnerProgram.objects.get(
            name=DEMO_PROGRAM_NAME,
            tag=DEMO_PROGRAM_TAG,
        )
        users = {
            spec["key"]: CustomUser.objects.get(email=spec["email"])
            for spec in DEMO_USER_SPECS
        }
        self.assertTrue(all(user.is_active for user in users.values()))
        self.assertTrue(
            all(user.check_password(self.demo_password) for user in users.values())
        )
        self.assertEqual(users["expert"].user_type, CustomUser.EXPERT)
        self.assertTrue(users["expert"].expert.programs.filter(pk=program.pk).exists())
        self.assertTrue(program.managers.filter(pk=users["manager"].pk).exists())
        self.assertEqual(
            PartnerProgramUserProfile.objects.filter(
                partner_program=program,
            ).count(),
            4,
        )

        application = Application.objects.get(program=program)
        self.assertEqual(application.status, Application.STATUS_SUBMITTED)
        self.assertEqual(
            application.participation_mode,
            Application.PARTICIPATION_MODE_TEAM,
        )
        team = Team.objects.get(application=application)
        self.assertEqual(
            TeamMember.objects.filter(
                team=team,
                status=TeamMember.STATUS_ACCEPTED,
            ).count(),
            2,
        )

        self.assertEqual(Criteria.objects.filter(partner_program=program).count(), 3)
        self.assertEqual(
            Criteria.objects.filter(
                partner_program=program,
                type="int",
            ).count(),
            2,
        )
        self.assertEqual(
            Criteria.objects.filter(
                partner_program=program,
                type="float",
            ).count(),
            1,
        )
        self.assertEqual(
            set(
                Criteria.objects.filter(partner_program=program).values_list(
                    "name",
                    flat=True,
                )
            ),
            {spec["name"] for spec in DEMO_CRITERION_SPECS},
        )
        self.assertEqual(Submission.objects.filter(program=program).count(), 3)
        self.assertEqual(
            SubmissionExpertAssignment.objects.filter(
                submission__program=program,
                expert=users["expert"].expert,
            ).count(),
            3,
        )

        submissions = {
            submission.stage_key: submission
            for submission in Submission.objects.filter(program=program)
        }
        without_evaluation = submissions["demo-without-evaluation"]
        draft_submission = submissions["demo-draft-evaluation"]
        submitted_submission = submissions["demo-submitted-evaluation"]
        self.assertFalse(
            Evaluation.objects.filter(submission=without_evaluation).exists()
        )
        draft = Evaluation.objects.get(submission=draft_submission)
        self.assertEqual(draft.status, Evaluation.STATUS_DRAFT)
        self.assertEqual(draft.scores.count(), 1)
        submitted = Evaluation.objects.get(submission=submitted_submission)
        self.assertEqual(submitted.status, Evaluation.STATUS_SUBMITTED)
        self.assertIsNotNone(submitted.submitted_at)
        self.assertEqual(submitted.scores.count(), 3)
        self.assertEqual(
            submitted_submission.expert_assignments.get().status,
            SubmissionExpertAssignment.STATUS_COMPLETED,
        )

    def test_repeated_run_does_not_create_duplicates(self):
        self.run_seed()
        first_ids = self.dataset_ids()

        self.run_seed()

        self.assertEqual(self.dataset_ids(), first_ids)
        self.assertEqual(len(first_ids["users"]), 4)
        self.assertEqual(len(first_ids["criteria"]), len(DEMO_CRITERION_SPECS))
        self.assertEqual(len(first_ids["submissions"]), len(DEMO_SUBMISSION_SPECS))
        self.assertEqual(len(first_ids["assignments"]), 3)
        self.assertEqual(len(first_ids["evaluations"]), 2)
        self.assertEqual(len(first_ids["scores"]), 4)

        program = PartnerProgram.objects.get(name=DEMO_PROGRAM_NAME)
        draft = Evaluation.objects.get(
            submission__program=program,
            status=Evaluation.STATUS_DRAFT,
        )
        extra_criterion = Criteria.objects.create(
            partner_program=program,
            name="[DEMO] Лишний критерий",
            description="Проверка точечной очистки DEV-072.",
            type="int",
            min_value=0,
            max_value=10,
        )
        extra_score = EvaluationScore.objects.create(
            evaluation=draft,
            criterion=extra_criterion,
            value=5,
        )

        self.run_seed()

        self.assertFalse(EvaluationScore.objects.filter(pk=extra_score.pk).exists())
        self.assertFalse(Criteria.objects.filter(pk=extra_criterion.pk).exists())
        self.assertEqual(self.dataset_ids(), first_ids)

    def test_dry_run_reports_counts_without_persisting_changes(self):
        stdout, _stderr = self.run_seed("--dry-run")

        self.assertIn("Пробный запуск завершен", stdout)
        self.assertIn("сдачи: 3", stdout)
        self.assert_demo_absent()

        self.run_seed()
        draft_score = EvaluationScore.objects.get(
            evaluation__submission__program__name=DEMO_PROGRAM_NAME,
            evaluation__status=Evaluation.STATUS_DRAFT,
        )
        draft_score.value = 3
        draft_score.save(update_fields=["value", "updated_at"])

        self.run_seed("--dry-run")

        draft_score.refresh_from_db()
        self.assertEqual(draft_score.value, 3)

    def test_reset_rebuilds_only_demo_contour(self):
        self.run_seed()
        original_program = PartnerProgram.objects.get(name=DEMO_PROGRAM_NAME)
        original_program_id = original_program.pk
        demo_user_ids = set(
            CustomUser.objects.filter(
                email__in=[spec["email"] for spec in DEMO_USER_SPECS]
            ).values_list("pk", flat=True)
        )
        outsider = create_user(prefix="demo-reset-outsider")
        outsider_program = create_partner_program(
            name="[DEMO] Похожая, но посторонняя программа",
            tag="other-demo-program",
        )

        self.run_seed("--reset")

        rebuilt = PartnerProgram.objects.get(
            name=DEMO_PROGRAM_NAME,
            tag=DEMO_PROGRAM_TAG,
        )
        self.assertNotEqual(rebuilt.pk, original_program_id)
        self.assertTrue(CustomUser.objects.filter(pk=outsider.pk).exists())
        self.assertTrue(PartnerProgram.objects.filter(pk=outsider_program.pk).exists())
        self.assertEqual(
            set(
                CustomUser.objects.filter(
                    email__in=[spec["email"] for spec in DEMO_USER_SPECS]
                ).values_list("pk", flat=True)
            ),
            demo_user_ids,
        )
        self.assertEqual(Submission.objects.filter(program=rebuilt).count(), 3)
        self.assertEqual(Criteria.objects.filter(partner_program=rebuilt).count(), 3)
        self.assertEqual(
            EvaluationScore.objects.filter(
                evaluation__submission__program=rebuilt,
            ).count(),
            4,
        )

    def test_expert_api_returns_three_expected_evaluation_states(self):
        self.run_seed()
        expert_user = CustomUser.objects.get(email="demo.expert@procollab.test")
        client = APIClient()
        client.force_authenticate(expert_user)

        response = client.get("/expert/submissions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        states = {
            (
                item["my_evaluation"]["status"]
                if item["my_evaluation"] is not None
                else "none"
            )
            for item in response.data["results"]
        }
        self.assertEqual(states, {"none", "draft", "submitted"})
        submitted_item = next(
            item
            for item in response.data["results"]
            if item["my_evaluation"]
            and item["my_evaluation"]["status"] == Evaluation.STATUS_SUBMITTED
        )
        self.assertEqual(
            submitted_item["assignment"]["status"],
            SubmissionExpertAssignment.STATUS_COMPLETED,
        )

    def test_expert_detail_is_pii_safe_for_all_demo_submissions(self):
        self.run_seed()
        expert_user = CustomUser.objects.get(email="demo.expert@procollab.test")
        participant_emails = {
            "demo.participant1@procollab.test",
            "demo.participant2@procollab.test",
        }
        client = APIClient()
        client.force_authenticate(expert_user)
        forbidden_keys = {
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

        for submission in Submission.objects.filter(program__name=DEMO_PROGRAM_NAME):
            with self.subTest(submission=submission.pk):
                response = client.get(f"/expert/submissions/{submission.pk}/")
                self.assertEqual(response.status_code, 200)
                self.assertFalse(forbidden_keys.intersection(response.data))
                serialized = str(response.data)
                self.assertTrue(
                    all(email not in serialized for email in participant_emails)
                )
                self.assertNotIn("private", serialized)
                self.assertEqual(response.data["title"], submission.title)
                self.assertEqual(response.data["description"], submission.description)
                self.assertEqual(response.data["links"], submission.links)

    def test_command_never_prints_the_demo_password(self):
        stdout, stderr = self.run_seed()

        self.assertNotIn(self.demo_password, stdout)
        self.assertNotIn(self.demo_password, stderr)

    def dataset_ids(self):
        program = PartnerProgram.objects.get(
            name=DEMO_PROGRAM_NAME,
            tag=DEMO_PROGRAM_TAG,
        )
        return {
            "users": tuple(
                CustomUser.objects.filter(
                    email__in=[spec["email"] for spec in DEMO_USER_SPECS]
                )
                .order_by("pk")
                .values_list("pk", flat=True)
            ),
            "programs": (program.pk,),
            "criteria": tuple(
                Criteria.objects.filter(partner_program=program)
                .order_by("pk")
                .values_list("pk", flat=True)
            ),
            "submissions": tuple(
                Submission.objects.filter(program=program)
                .order_by("pk")
                .values_list("pk", flat=True)
            ),
            "assignments": tuple(
                SubmissionExpertAssignment.objects.filter(submission__program=program)
                .order_by("pk")
                .values_list("pk", flat=True)
            ),
            "evaluations": tuple(
                Evaluation.objects.filter(submission__program=program)
                .order_by("pk")
                .values_list("pk", flat=True)
            ),
            "scores": tuple(
                EvaluationScore.objects.filter(evaluation__submission__program=program)
                .order_by("pk")
                .values_list("pk", flat=True)
            ),
        }
