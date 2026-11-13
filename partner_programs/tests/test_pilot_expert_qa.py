from django.test import TestCase, override_settings

from deploy.pilot.prepare_expert_qa import prepare_fixture
from partner_programs.models import PartnerProgram
from project_rates.models import ProjectExpertAssignment, ProjectScore
from project_rates.program_experts import can_evaluate_program
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_program,
    create_rate_project,
    create_rate_user,
)
from users.models import CustomUser


class PilotExpertFixtureTests(TestCase):
    def setUp(self):
        self.primary = create_rate_program()
        self.original_criteria = list(
            self.primary.criterias.values_list("pk", "name", "type")
        )
        self.mode = override_settings(
            WHITE_LABEL_ENABLED=True,
            WHITE_LABEL_PROGRAM_ID=self.primary.pk,
            WHITE_LABEL_BRAND_NAME="Проверка",
            WHITE_LABEL_FRONTEND_URL="http://127.0.0.1:18461",
            WHITE_LABEL_LOGO_URL="",
            WHITE_LABEL_FAVICON_URL="",
            PROGRAM_SOLUTIONS_ENABLED=False,
        )
        self.mode.enable()
        self.addCleanup(self.mode.disable)

    def prepare(self):
        return prepare_fixture(
            key="unit-expert-20261113", password="isolated-qa-password-only", local=True
        )

    def test_separate_work_graph_preserves_roles_and_primary_programme(self):
        result = self.prepare()
        manager = CustomUser.objects.get(pk=result["manager_user_id"])
        expert = CustomUser.objects.get(pk=result["expert_user_id"])
        self.assertEqual(manager.user_type, CustomUser.MEMBER)
        self.assertEqual(expert.user_type, CustomUser.MEMBER)
        self.assertTrue(can_evaluate_program(manager, result["program_id"]))
        self.assertFalse(manager.expert.project_assignments.exists())
        self.assertEqual(expert.expert.project_assignments.count(), 4)
        self.assertFalse(
            ProjectExpertAssignment.objects.filter(partner_program=self.primary).exists()
        )
        self.assertEqual(
            list(self.primary.criterias.values_list("pk", "name", "type")),
            self.original_criteria,
        )
        self.assertEqual(ProjectScore.objects.count(), 1)
        self.assertEqual(ProjectScore.objects.get().value, "0")
        self.assertTrue(result["existing_scores_unchanged"])

    def test_existing_primary_score_is_not_rewritten(self):
        score = ProjectScore.objects.create(
            project=create_rate_project(),
            criteria=create_rate_criteria(self.primary),
            user=create_rate_user(),
            value="7",
        )
        self.prepare()
        score.refresh_from_db()
        self.assertEqual(score.value, "7")

    def test_existing_fixture_is_refused_without_replacing_its_scores(self):
        self.prepare()
        before = list(ProjectScore.objects.values_list("pk", "value"))
        users = CustomUser.objects.count()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(list(ProjectScore.objects.values_list("pk", "value")), before)
        self.assertEqual(CustomUser.objects.count(), users)

    def test_non_pilot_destination_is_refused_before_any_fixture_writes(self):
        before = PartnerProgram.objects.count()
        with self.assertRaises(ValueError):
            prepare_fixture(
                key="unit-expert-20261113", password="isolated-qa-password-only"
            )
        self.assertEqual(PartnerProgram.objects.count(), before)
