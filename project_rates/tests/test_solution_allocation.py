from unittest.mock import patch

from django.core import signing
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)

from partner_programs.tests.test_solution_forms import call
from project_rates import solution_allocation, solution_assignments
from project_rates.models import ExpertCaseScope
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.tests.helpers import create_rate_expert
from users.models import Expert
from project_rates.tests.test_solution_evaluation import EvaluationFixture
from project_rates.tests import test_solution_evaluation as evaluation_tests


class AllocationFixture(EvaluationFixture):
    def setup_allocation(self):
        self.seed_evaluation()
        self.program.required_evaluators = 2
        self.program.save()
        self.root = f"/programs/{self.program.pk}/management/solution-evaluation/"

    def plan(self, **changes):
        command = dict(
            revision=solution_assignments.revision(self.program),
            expert_ids=[self.second.expert.pk],
        )
        command.update(changes)
        return call(self.manager, "post", self.root + "allocation/", command)

    def apply(self, token, actor=None):
        return call(
            actor or self.manager,
            "post",
            self.root + "allocation/apply/",
            dict(plan_token=token),
        )


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionAllocationTests(AllocationFixture, TestCase):
    def setUp(self):
        self.setup_allocation()

    def test_preview_is_read_only_and_apply_uses_actual_solution_identity_once(self):
        response = self.plan()
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("SolutionAllocationPlan", response.data)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 1)
        self.assertEqual(response.data["assignments"][0]["solution_id"], self.solution.pk)
        self.assertNotIn("project_id", str(response.data))
        self.assertFalse(response.data["shortages"])
        applied = self.apply(response.data["plan_token"])
        self.assertEqual(applied.status_code, 200, applied.data)
        self.assert_schema("SolutionAssignmentReceipt", applied.data)
        self.assertEqual(applied.data["created"], 1)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 2)
        self.assert_error(
            self.apply(response.data["plan_token"]), "stale_assignments", 409
        )

    def test_shortage_never_applies_partial_plan(self):
        self.program.required_evaluators = 3
        self.program.save()
        response = self.plan()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["shortages"][0]["missing"], 1)
        self.assert_error(self.apply(response.data["plan_token"]), "expert_shortage", 409)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 1)

    def test_case_pools_and_scopes_constrain_new_assignments(self):
        scope = ExpertCaseScope.objects.create(
            partner_program=self.program,
            expert=self.second.expert,
            all_cases=False,
            case_names=[],
        )
        self.assertTrue(self.plan().data["shortages"])
        self.assert_error(
            self.plan(
                case_pools=[
                    dict(case_name="Задача 1", expert_ids=[self.second.expert.pk])
                ]
            ),
            "invalid_assignments",
            400,
        )
        scope.case_names = ["Задача 1"]
        scope.save()
        response = self.plan(
            case_pools=[dict(case_name="Задача 1", expert_ids=[self.second.expert.pk])]
        )
        self.assertEqual(len(response.data["assignments"]), 1)
        self.assertTrue(self.plan(case_pools=[]).data["shortages"])
        self.assert_error(
            self.plan(case_pools=[dict(case_name="Foreign", expert_ids=[])]),
            "invalid_assignments",
            400,
        )

    def test_own_team_is_excluded_even_when_expert_is_in_case_pool(self):
        self.captain.is_active = True
        self.captain.save(update_fields=["is_active"])
        expert, _ = Expert.objects.get_or_create(user=self.captain)
        expert.programs.add(self.program)
        response = self.plan(
            expert_ids=[expert.pk],
            case_pools=[dict(case_name="Задача 1", expert_ids=[expert.pk])],
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["assignments"], [])
        self.assertEqual(response.data["shortages"][0]["missing"], 1)

    def test_foreign_and_draft_solutions_and_duplicate_ids_are_rejected(self):
        draft = self.another_solution(submitted=False)
        for changes in [
            dict(solution_ids=[draft.pk]),
            dict(solution_ids=[2**53 - 1]),
            dict(expert_ids=[2**53 - 1]),
            dict(expert_ids=[self.second.expert.pk] * 2),
            dict(solution_ids=[self.solution.pk] * 2),
            dict(expert_ids=[]),
            dict(assignment_overrides=[dict(solution_id=draft.pk, expert_ids=[])]),
            dict(
                assignment_overrides=[
                    dict(
                        solution_id=self.solution.pk,
                        expert_ids=[self.second.expert.pk] * 2,
                    )
                ]
            ),
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.plan(**changes).status_code, 400)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 1)

    def test_changed_membership_case_scope_or_solution_invalidates_plan(self):
        token = self.plan().data["plan_token"]
        self.program.experts.remove(self.second.expert)
        self.assert_error(self.apply(token), "stale_assignments", 409)
        self.program.experts.add(self.second.expert)
        token = self.plan().data["plan_token"]
        ExpertCaseScope.objects.create(
            partner_program=self.program,
            expert=self.second.expert,
            all_cases=False,
            case_names=[],
        )
        self.assert_error(self.apply(token), "stale_assignments", 409)

    def test_token_tampering_other_domain_foreign_program_and_expiry(self):
        token = self.plan().data["plan_token"]
        self.assert_error(self.apply(token + "broken"), "stale_plan", 409)
        self.assert_error(
            self.apply(
                signing.dumps(dict(program_id=self.program.pk), salt="expert-allocation")
            ),
            "stale_plan",
            409,
        )
        self.assert_error(
            self.apply(
                signing.dumps(
                    dict(program_id=self.program.pk + 1), salt=solution_allocation.SALT
                )
            ),
            "invalid_plan",
            400,
        )
        with patch("django.core.signing.time.time", return_value=10):
            expired = self.plan().data["plan_token"]
        self.assert_error(self.apply(expired), "stale_plan", 409)

    def test_reroll_and_override_preserve_existing_assignments_and_balanced_load(self):
        third = create_rate_expert(program=self.program)
        ids = [self.second.expert.pk, third.expert.pk]
        first = self.plan(expert_ids=ids)
        self.assertTrue(first.data["can_reroll"])
        reroll = self.plan(expert_ids=ids, previous_plan_token=first.data["plan_token"])
        self.assertEqual(reroll.status_code, 200, reroll.data)
        self.assertNotEqual(first.data["assignments"], reroll.data["assignments"])
        override = self.plan(
            expert_ids=ids,
            assignment_overrides=[
                dict(solution_id=self.solution.pk, expert_ids=[third.expert.pk])
            ],
        )
        self.assertEqual(override.data["assignments"][0]["expert_id"], third.expert.pk)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 1)

    def test_quota_preview_and_save_keep_surplus_and_scores(self):
        SolutionExpertAssignment.objects.create(
            partner_program=self.program,
            solution=self.solution,
            expert=self.second.expert,
        )
        self.rate()
        response = call(self.manager, "get", self.root + "quota/?required_evaluators=1")
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("SolutionQuota", response.data)
        self.assertEqual(response.data["ready_before"], 0)
        self.assertEqual(response.data["ready_after"], 1)
        self.assertEqual(response.data["surplus_assignments"], 1)
        saved = call(
            self.manager,
            "put",
            self.root + "quota/",
            dict(revision=response.data["revision"], required_evaluators=1),
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 2)
        self.assertEqual(SolutionScore.objects.count(), 3)
        self.assertEqual(self.assign([self.solution.pk], self.second).status_code, 200)

    def test_legacy_scores_are_virtual_assignments_in_preview_then_preserved_on_opt_in(
        self,
    ):
        self.assignment.delete()
        self.program.required_evaluators = None
        self.program.is_distributed_evaluation = False
        self.program.max_project_rates = 2
        self.program.save()
        SolutionScore.objects.create(
            solution=self.solution, user=self.expert, criteria=self.criteria[0], value="5"
        )
        response = self.plan(expert_ids=[self.expert.expert.pk, self.second.expert.pk])
        self.assertEqual(len(response.data["assignments"]), 1)
        self.assertEqual(
            response.data["assignments"][0]["expert_id"], self.second.expert.pk
        )
        self.assertFalse(SolutionExpertAssignment.objects.exists())
        self.assertEqual(self.apply(response.data["plan_token"]).status_code, 200)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 2)

    def test_shared_invitation_workspace_uses_solution_revision_and_backfills_own_scores(
        self,
    ):
        from project_rates.workspace import revision, enable_workspace

        self.assignment.delete()
        self.program.required_evaluators = None
        self.program.is_distributed_evaluation = False
        self.program.save()
        before = revision(self.program)
        SolutionScore.objects.create(
            solution=self.solution, user=self.expert, criteria=self.criteria[0], value="1"
        )
        self.assertNotEqual(before, revision(self.program))
        self.assertEqual(
            revision(self.program), solution_assignments.revision(self.program)
        )
        enable_workspace(self.program)
        self.assertTrue(
            SolutionExpertAssignment.objects.filter(
                solution=self.solution, expert=self.expert.expert
            ).exists()
        )

    def test_results_are_private_manager_only_and_match_contract(self):
        self.rate()
        url = f"/programs/{self.program.pk}/management/solution-results/"
        response = call(self.manager, "get", url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("SolutionResults", response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        for actor in [self.expert, self.captain, self.second]:
            self.assertEqual(call(actor, "get", url).status_code, 403)
            self.assertEqual(
                self.apply(self.plan().data["plan_token"], actor).status_code, 403
            )
        self.assertEqual(call(self.manager, "get", url + "?scope=all").status_code, 400)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionAllocationRaceTests(AllocationFixture, TransactionTestCase):
    race = evaluation_tests.SolutionEvaluationRaceTests.race

    def setUp(self):
        self.setup_allocation()

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_plans_cannot_both_fill_one_slot(self):
        third = create_rate_expert(program=self.program)
        plans = [
            self.plan(expert_ids=[user.expert.pk]).data["plan_token"]
            for user in [self.second, third]
        ]
        actions = [
            lambda token=token: solution_allocation.apply_allocation(
                program_id=self.program.pk, actor=self.manager, plan_token=token
            )
            for token in plans
        ]
        self.assertCountEqual(self.race(*actions), ["ok", "stale_assignments"])
        self.assertEqual(SolutionExpertAssignment.objects.count(), 2)
