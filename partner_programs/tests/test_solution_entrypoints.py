from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from partner_programs import selectors
from partner_programs.services.analytics import (
    _get_participant_metrics,
    participants_without_team_rows,
)
from partner_programs.solution_api import create_solution
from partner_programs.solution_models import ProgramSolutionMember, SolutionInvitation
from partner_programs.tests.helpers import create_user, create_program_member
from partner_programs.tests.test_solution_forms import FormFixture
from partner_programs.tests.test_solution_foundation import solution_program
from project_rates import solution_evaluation
from project_rates.solution_models import SolutionScore
from project_rates.tests.test_solution_evaluation import EvaluationFixture
from vacancy.mapping import get_link, create_text_for_email


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionParticipantEntrypointsTests(FormFixture, TestCase):
    def setUp(self):
        self.seed()
        self.accepted, self.pending, self.other = [create_user() for _ in range(3)]
        for user in [self.accepted, self.pending, self.other]:
            create_program_member(self.program, user=user)
        ProgramSolutionMember.objects.create(solution=self.solution, user=self.accepted)
        SolutionInvitation.objects.create(
            solution=self.solution, recipient=self.pending, role="Аналитик"
        )

    def test_mail_selectors_and_attention_list_agree_on_accepted_team_and_pending(self):
        expected = {self.pending.pk, self.other.pk}
        self.assertEqual(
            set(
                selectors.program_participants_without_project(
                    self.program.pk
                ).values_list("pk", flat=True)
            ),
            expected,
        )
        self.assertEqual(
            set(
                selectors.program_participants_without_project_registered_on(
                    self.program.pk, timezone.localdate()
                ).values_list("pk", flat=True)
            ),
            expected,
        )
        self.assertEqual(
            set(
                participants_without_team_rows(self.program.pk).values_list(
                    "user_id", flat=True
                )
            ),
            expected,
        )
        metrics = _get_participant_metrics(self.program.pk)
        self.assertEqual(metrics["with_team"], 2)
        self.assertEqual(metrics["without_team"], 2)
        self.assertEqual(metrics["project_creators"], 1)
        self.assertEqual(
            set(
                selectors.program_participants_with_unsubmitted_project(
                    self.program.pk
                ).values_list("pk", flat=True)
            ),
            {self.captain.pk, self.accepted.pk},
        )

    def test_team_in_another_program_does_not_remove_participant_from_current_list(self):
        other = solution_program(is_competitive=True)
        create_program_member(other, user=self.other)
        create_solution(other.pk, self.other, {})
        self.assertIn(
            self.other.pk,
            selectors.program_participants_without_project(self.program.pk).values_list(
                "pk", flat=True
            ),
        )

    def test_legacy_destructive_handlers_cannot_remove_solution_registration_or_use_solution_as_link(
        self,
    ):
        from partner_programs.models import PartnerProgramUserProfile
        from partner_programs.services.participant_removal import (
            preview_removal,
            remove_participants,
            RemovalConflict,
        )
        from partner_programs.services.management_project_actions import (
            load_links,
            ActionConflict,
        )

        profile = PartnerProgramUserProfile.objects.get(
            partner_program=self.program, user=self.captain
        )
        with self.assertRaises(RemovalConflict):
            preview_removal(self.program.pk, self.manager, [profile.pk])
        with self.assertRaises(RemovalConflict):
            remove_participants(self.program.pk, self.manager, [profile.pk], "unused")
        with self.assertRaises(ActionConflict):
            load_links(self.program, [self.solution.pk])
        self.assertTrue(PartnerProgramUserProfile.objects.filter(pk=profile.pk).exists())
        self.assertTrue(
            ProgramSolutionMember.objects.filter(
                solution=self.solution, user=self.captain
            ).exists()
        )


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EXPERT_WORKSPACE_FRONTEND_URL="https://dev.procollab.ru/",
)
class SolutionRatingNotificationTests(EvaluationFixture, TestCase):
    def setUp(self):
        self.seed_evaluation()

    @patch("project_rates.solution_notifications.send_email.delay")
    def test_success_queues_captain_notice_after_commit_with_real_program_and_solution(
        self, send
    ):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.rate()
            send.assert_not_called()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(callbacks), 1)
        send.assert_called_once()
        payload = send.call_args.args[0]
        self.assertEqual(payload["message_type"], "solution_rated")
        self.assertEqual(payload["user_id"], self.captain.pk)
        self.assertEqual(payload["program_id"], self.program.pk)
        self.assertEqual(payload["solution_id"], self.solution.pk)
        self.assertNotIn("project_id", payload)
        self.assertEqual(
            get_link(payload),
            f"https://dev.procollab.ru/office/program/{self.program.pk}/solutions/{self.solution.pk}",
        )
        self.assertIn(self.solution.name, create_text_for_email(payload))
        self.assertNotIn("scores", payload)

    @patch("project_rates.solution_notifications.send_email.delay")
    def test_rollback_or_invalid_score_does_not_queue_notice(self, send):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    solution_evaluation.rate_solution(
                        program_id=self.program.pk,
                        solution_id=self.solution.pk,
                        actor=self.expert,
                        **self.scores(),
                    )
                    raise RuntimeError("Rollback")
        self.assertFalse(SolutionScore.objects.exists())
        send.assert_not_called()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.rate(
                scores=[dict(criterion_id=self.criteria[0].pk, value="NaN")]
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(callbacks, [])
        send.assert_not_called()
