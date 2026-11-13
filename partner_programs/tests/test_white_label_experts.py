from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from partner_programs.services.white_label_experts import ensure_organizer_experts
from project_rates.models import (
    Criteria,
    ExpertCaseScope,
    ProjectExpertAssignment,
    ProjectScore,
)
from project_rates.tests.helpers import (
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)
from project_rates.criteria_policy import revision
from users.models import Expert, Member


class WhiteLabelOrganizerExpertTests(TestCase):
    def setUp(self):
        self.program = create_rate_program()
        self.other = create_rate_program()
        self.user = create_rate_user()
        mode = override_settings(
            WHITE_LABEL_ENABLED=True,
            WHITE_LABEL_ORGANIZERS_ARE_EXPERTS=True,
            WHITE_LABEL_PROGRAM_ID=self.program.pk,
            WHITE_LABEL_BRAND_NAME="Кейс-чемпионат",
            WHITE_LABEL_FRONTEND_URL="https://pilot.example.test",
            WHITE_LABEL_LOGO_URL="",
        )
        mode.enable()
        self.addCleanup(mode.disable)

    def evaluation(self):
        self.program.criterias.all().delete()
        self.program.is_competitive = True
        self.program.required_evaluators = 1
        self.program.save()
        criterion = Criteria.objects.create(
            partner_program=self.program,
            name="Решение",
            type="int",
            min_value=0,
            max_value=10,
        )
        self.program.managers.add(self.user)
        project = create_rate_project()
        self.program.users.add(
            project.leader, through_defaults={"partner_program_data": {}}
        )
        link = link_project_to_program(self.program, project)
        type(link).objects.filter(pk=link.pk).update(submitted=True)
        ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=project, expert=self.user.expert
        )
        api = APIClient()
        api.force_authenticate(self.user)
        return (
            api,
            project,
            criterion,
            {
                "expected_revision": revision(self.program),
                "scores": [{"criterion_id": criterion.pk, "value": "8"}],
            },
        )

    def test_member_organizer_can_actually_evaluate_without_legacy_email_schema(self):
        api, project, criterion, body = self.evaluation()
        self.assertTrue(api.get("/auth/users/current/").data["has_evaluation_access"])
        self.assertEqual(
            api.get(f"/rate-project/{self.program.pk}?assigned_only=1").data["count"], 1
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = api.post(f"/rate-project/rate/{project.pk}", body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            ProjectScore.objects.get(criteria=criterion, user=self.user).value, "8"
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://pilot.example.test/office/program/", mail.outbox[0].body)
        self.assertNotIn("PROCOLLAB", mail.outbox[0].body + mail.outbox[0].subject)

    def test_notification_failure_does_not_turn_a_saved_score_into_an_api_error(self):
        from unittest.mock import patch

        api, project, criterion, body = self.evaluation()
        with patch(
            "project_rates.tasks.send_white_label_project_rated.delay",
            side_effect=RuntimeError("synthetic mail failure"),
        ):
            with self.assertLogs(level="ERROR"), self.captureOnCommitCallbacks(
                execute=True
            ):
                response = api.post(
                    f"/rate-project/rate/{project.pk}", body, format="json"
                )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            ProjectScore.objects.filter(criteria=criterion, user=self.user).exists()
        )

    def test_add_manager_grants_program_expert_and_keeps_member_management_and_settings(
        self,
    ):
        self.program.managers.add(self.user)
        self.user.refresh_from_db()
        self.assertTrue(self.program.experts.filter(user=self.user).exists())
        self.assertTrue(self.program.managers.filter(pk=self.user.pk).exists())
        self.assertTrue(Member.objects.filter(user=self.user).exists())
        self.assertEqual(self.user.user_type, self.user.MEMBER)
        self.assertFalse(self.user.is_staff or self.user.is_superuser)
        self.assertFalse(self.other.experts.filter(user=self.user).exists())
        self.assertFalse(ProjectExpertAssignment.objects.exists())
        self.assertEqual(len(mail.outbox), 0)
        self.program.refresh_from_db()
        self.assertFalse(self.program.is_distributed_evaluation)

    def test_bootstrap_is_idempotent_and_preserves_existing_scope(self):
        with override_settings(WHITE_LABEL_ORGANIZERS_ARE_EXPERTS=False):
            self.program.managers.add(self.user)
        expert = Expert.objects.create(user=self.user)
        expert.programs.add(self.other)
        scope = ExpertCaseScope.objects.create(
            partner_program=self.program,
            expert=expert,
            all_cases=False,
            case_names=["Право"],
        )
        self.assertEqual(ensure_organizer_experts(self.program.pk), 1)
        self.assertEqual(ensure_organizer_experts(self.program.pk), 0)
        call_command("ensure_white_label_organizer_experts", stdout=StringIO())
        scope.refresh_from_db()
        self.assertEqual((scope.all_cases, scope.case_names), (False, ["Право"]))
        self.assertEqual(expert.programs.count(), 2)
        self.assertEqual(Expert.objects.filter(user=self.user).count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_reverse_manager_add_is_supported(self):
        self.user.managed_partner_programs.add(self.program, self.other)
        self.assertEqual(
            list(self.user.expert.programs.values_list("pk", flat=True)),
            [self.program.pk],
        )

    def test_default_flag_disabled_and_other_programs_and_participants_do_not_grant_roles(
        self,
    ):
        self.other.managers.add(self.user)
        self.program.users.add(self.user, through_defaults={"partner_program_data": {}})
        self.assertEqual(ensure_organizer_experts(self.other.pk), 0)
        self.assertFalse(Expert.objects.filter(user=self.user).exists())
        with override_settings(WHITE_LABEL_ORGANIZERS_ARE_EXPERTS=False):
            self.program.managers.add(self.user)
            self.assertEqual(ensure_organizer_experts(self.program.pk), 0)
        with override_settings(WHITE_LABEL_ENABLED=False):
            self.assertEqual(ensure_organizer_experts(self.program.pk), 0)
        self.assertFalse(Expert.objects.filter(user=self.user).exists())

    def test_inactive_manager_is_not_granted_expert_access(self):
        self.user.is_active = False
        self.user.save()
        self.program.managers.add(self.user)
        self.assertFalse(Expert.objects.filter(user=self.user).exists())
