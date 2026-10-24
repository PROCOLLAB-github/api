import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.http import Http404
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.utils import timezone

from partner_programs.solution_api import create_solution
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_submission import submit_solution
from partner_programs.solution_schema import form_data
from partner_programs.tests.helpers import (
    create_user,
    create_program_member,
    create_partner_program,
)
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_submission import SubmissionFixture
from project_rates import solution_assignments, solution_evaluation
from project_rates.criteria_policy import revision, locked
from project_rates.models import Criteria, ExpertCaseScope, ProjectScore
from project_rates.solution_models import SolutionScore, SolutionExpertAssignment
from project_rates.tests.helpers import create_rate_expert, create_rate_criteria
from users.models import Expert


class EvaluationFixture(SubmissionFixture):
    def seed_evaluation(self):
        self.ready()
        response = self.submit()
        assert response.status_code == 200, response.data
        self.solution.refresh_from_db()
        self.expert = create_rate_expert(program=self.program)
        self.second = create_rate_expert(program=self.program)
        Criteria.objects.filter(partner_program=self.program).delete()
        self.criteria = [
            create_rate_criteria(self.program, type="int", min_value=0, max_value=10),
            create_rate_criteria(self.program, type="bool"),
            create_rate_criteria(self.program, type="str"),
        ]
        self.program.required_evaluators = 1
        self.program.is_distributed_evaluation = True
        self.program.save()
        self.assignment = SolutionExpertAssignment.objects.create(
            partner_program=self.program,
            solution=self.solution,
            expert=self.expert.expert,
        )
        self.evaluation_url = self.url + "evaluation/"
        self.list_url = f"/programs/{self.program.pk}/solution-evaluation/"

    def scores(self, **changes):
        values = dict(
            expected_criteria_revision=revision(self.program),
            scores=[
                dict(criterion_id=self.criteria[0].pk, value="0"),
                dict(criterion_id=self.criteria[1].pk, value="False"),
            ],
        )
        values.update(changes)
        return values

    def rate(self, actor=None, **changes):
        return call(
            actor or self.expert, "post", self.evaluation_url, self.scores(**changes)
        )

    def options_url(self, actor=None):
        return (
            f"/programs/{self.program.pk}/management/solution-evaluation/experts/"
            f"{(actor or self.expert).expert.pk}/assignments/"
        )

    def options(self, actor=None):
        response = call(self.manager, "get", self.options_url(actor))
        assert response.status_code == 200, response.data
        return response.data

    def assign(self, ids, actor=None, **changes):
        command = dict(revision=self.options(actor)["revision"], solution_ids=ids)
        command.update(changes)
        return call(self.manager, "put", self.options_url(actor), command)

    def assert_schema(self, name, data):
        from jsonschema import Draft202012Validator, FormatChecker

        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(
            {"components": spec["components"], "$ref": f"#/components/schemas/{name}"},
            format_checker=FormatChecker(),
        ).validate(data)

    def another_solution(self, *, submitted=True):
        captain = create_user()
        create_program_member(self.program, user=captain)
        solution, _ = create_solution(
            self.program.pk, captain, dict(name="Вторая работа")
        )
        if submitted:
            from partner_programs.solution_answers import update_solution

            update_solution(
                program_id=self.program.pk,
                solution_id=solution.pk,
                actor=captain,
                expected_version=solution.version,
                expected_form_revision=form_data(self.program)["revision"],
                answers=[
                    dict(field_id=self.fields["select"]["id"], value="Задача 1"),
                    dict(field_id=self.fields["textarea"]["id"], value="Ответ"),
                ],
            )
            solution.refresh_from_db()
            submit_solution(
                program_id=self.program.pk,
                solution_id=solution.pk,
                actor=captain,
                expected_version=solution.version,
                expected_form_revision=form_data(self.program)["revision"],
            )
            solution.refresh_from_db()
        return solution


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionEvaluationTests(EvaluationFixture, TestCase):
    def setUp(self):
        self.seed_evaluation()

    def test_frame_is_snapshot_and_only_own_values_with_real_solution_identity(self):
        SolutionScore.objects.create(
            solution=self.solution, user=self.second, criteria=self.criteria[0], value="9"
        )
        response = call(self.expert, "get", self.evaluation_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("RatingFrame", response.data)
        self.assertEqual(response.data["solution"]["id"], self.solution.pk)
        self.assertTrue(response.data["solution"]["form"]["is_snapshot"])
        self.assertTrue(response.data["can_rate"])
        self.assertEqual([c["value"] for c in response.data["criteria"]], [None] * 3)
        self.assertNotIn("project_id", str(response.data))
        self.assertFalse(ProjectScore.objects.exists())

    def test_managed_save_zero_false_optional_comment_edit_and_permanent_freeze(self):
        response = self.rate()
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("RatingFrame", response.data)
        self.assertTrue(response.data["is_completed"])
        self.assertEqual(response.data["rated_count"], 1)
        self.assertEqual(
            [c["value"] for c in response.data["criteria"]], ["0", "False", ""]
        )
        self.assertEqual(self.rate().status_code, 200)
        self.assertEqual(SolutionScore.objects.count(), 3)
        self.assertTrue(locked(self.program))
        SolutionScore.objects.all().delete()
        self.program.refresh_from_db()
        self.assertTrue(locked(self.program))
        self.criteria[0].name = "Changed"
        with self.assertRaises(ValidationError):
            self.criteria[0].save()

    def test_invalid_values_foreign_duplicates_and_missing_are_atomic_and_address_criterion(
        self,
    ):
        for value in ["NaN", "Infinity", "-1", "11", "1.5", None]:
            with self.subTest(value=value):
                response = self.rate(
                    scores=[dict(criterion_id=self.criteria[0].pk, value=value)]
                )
                self.assert_error(response, "invalid_scores", 400)
                self.assert_schema("Error", response.data)
                self.assertEqual(
                    response.data["errors"][0]["criterion_id"], self.criteria[0].pk
                )
                self.assertIsNone(response.data["errors"][0]["field_id"])
                self.assertFalse(SolutionScore.objects.exists())
        rows = self.scores()["scores"]
        for extra, code in [
            (rows[0], "duplicate_criterion"),
            (dict(criterion_id=2**53 - 1, value="1"), "unknown_criterion"),
        ]:
            response = self.rate(scores=[*rows, extra])
            self.assert_error(response, "invalid_scores", 400)
            self.assertEqual(response.data["errors"][0]["code"], code)
            self.assertFalse(SolutionScore.objects.exists())

    def test_strict_wire_values_and_long_comment_do_not_coerce_or_write(self):
        for value in [0, False, {}, "x" * 51]:
            response = self.rate(
                scores=[dict(criterion_id=self.criteria[2].pk, value=value)]
            )
            self.assertEqual(response.status_code, 400, response.data)
            self.assertFalse(SolutionScore.objects.exists())
        self.assertEqual(self.rate(scores=[]).status_code, 400)

    def test_criteria_revision_conflict_and_deadline(self):
        response = self.rate(expected_criteria_revision="0" * 64)
        self.assert_error(response, "criteria_changed", 409)
        self.assertEqual(
            response.data["meta"]["current_criteria_revision"], revision(self.program)
        )
        self.program.datetime_evaluation_ends = timezone.now() - timezone.timedelta(
            seconds=1
        )
        self.program.save()
        self.assert_error(self.rate(), "evaluation_closed", 409)
        frame = call(self.expert, "get", self.evaluation_url)
        self.assertFalse(frame.data["can_rate"])
        self.assertFalse(SolutionScore.objects.exists())

    def test_roles_scope_unassigned_hidden_and_team_own_managed_forbidden(self):
        self.assertEqual(call(self.second, "get", self.evaluation_url).status_code, 404)
        self.assertEqual(self.rate(self.second).status_code, 404)
        self.assert_error(
            call(self.manager, "get", self.evaluation_url), "not_program_expert", 403
        )
        self.assertEqual(
            call(create_rate_expert(), "get", self.evaluation_url).status_code, 404
        )
        self.assert_error(
            call(self.captain, "get", self.list_url), "not_program_expert", 403
        )
        owner_expert, _ = Expert.objects.get_or_create(user=self.captain)
        self.captain.is_active = True
        self.captain.save(update_fields=["is_active"])
        owner_expert.programs.add(self.program)
        self.program.is_distributed_evaluation = False
        self.program.save()
        self.assert_error(self.rate(self.captain), "own_team", 403)
        draft = self.another_solution(submitted=False)
        self.assertEqual(
            call(
                self.expert,
                "get",
                f"/programs/{self.program.pk}/solutions/{draft.pk}/evaluation/",
            ).status_code,
            404,
        )

    def test_list_filters_before_pagination_status_own_completion_and_invalid_case(self):
        self.another_solution(submitted=False)
        response = call(self.expert, "get", self.list_url + "?limit=1&status=pending")
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("RatingPage", response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["application"]["solution_id"], self.solution.pk
        )
        self.assertEqual(call(self.second, "get", self.list_url).data["count"], 0)
        self.rate()
        self.assertEqual(
            call(self.expert, "get", self.list_url + "?status=pending").data["count"], 0
        )
        self.assertEqual(
            call(self.expert, "get", self.list_url + "?status=completed").data["count"], 1
        )
        self.assertEqual(
            call(self.expert, "get", self.list_url + "?search=nomatch").data["count"], 0
        )
        self.assert_error(
            call(
                self.expert,
                "get",
                self.list_url + "?case_scope=selected&case_name=foreign",
            ),
            "invalid_filter",
            400,
        )

    def test_legacy_open_partial_limit_and_existing_rater_can_edit(self):
        self.program.required_evaluators = None
        self.program.is_distributed_evaluation = False
        self.program.max_project_rates = 1
        self.program.save()
        rows = [dict(criterion_id=self.criteria[0].pk, value="3")]
        first = self.rate(scores=rows)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertFalse(first.data["is_completed"])
        self.assertEqual(first.data["rated_count"], 1)
        self.assert_error(self.rate(self.second, scores=rows), "max_rates_reached", 409)
        self.assertEqual(self.rate(scores=rows).status_code, 200)

    def test_assignment_revision_permissions_foreign_and_draft_are_atomic(self):
        options = self.options()
        self.assert_schema("AssignmentOptions", options)
        self.assertEqual(options["expert_id"], self.expert.expert.pk)
        self.assertEqual(call(self.expert, "get", self.options_url()).status_code, 403)
        self.assert_error(self.assign([], revision="0" * 64), "stale_assignments", 409)
        draft = self.another_solution(submitted=False)
        self.assert_error(self.assign([draft.pk]), "invalid_assignments", 400)
        self.assert_error(self.assign([2**53 - 1]), "invalid_assignments", 400)
        self.assert_error(
            self.assign([self.solution.pk, self.solution.pk]), "invalid_assignments", 400
        )
        self.assertEqual(SolutionExpertAssignment.objects.count(), 1)

    def test_assignment_quota_scope_remove_and_protect_partial_scores(self):
        self.assert_error(
            self.assign([self.solution.pk], self.second), "expert_limit_reached", 409
        )
        self.assertEqual(self.assign([]).status_code, 200)
        scope = ExpertCaseScope.objects.create(
            partner_program=self.program,
            expert=self.second.expert,
            all_cases=False,
            case_names=[],
        )
        self.assert_error(
            self.assign([self.solution.pk], self.second), "invalid_assignments", 400
        )
        scope.case_names = ["Задача 1"]
        scope.save()
        self.assertEqual(self.assign([self.solution.pk], self.second).status_code, 200)
        SolutionScore.objects.create(
            solution=self.solution, user=self.second, criteria=self.criteria[0], value="5"
        )
        self.assert_error(self.assign([], self.second), "scores_protected", 409)
        with self.assertRaises(ValidationError):
            SolutionExpertAssignment.objects.filter(expert=self.second.expert).delete()
        self.assertTrue(self.options(self.second)["solutions"][0]["protected"])
        scope.case_names = []
        scope.save()
        self.assertEqual(call(self.second, "get", self.evaluation_url).status_code, 200)

    def test_explicit_assignment_opt_in_preserves_historical_scores(self):
        self.assignment.delete()
        self.program.required_evaluators = None
        self.program.is_distributed_evaluation = False
        self.program.max_project_rates = 2
        self.program.save()
        SolutionScore.objects.create(
            solution=self.solution, user=self.expert, criteria=self.criteria[0], value="4"
        )
        self.assert_error(self.assign([]), "scores_protected", 409)
        self.program.refresh_from_db()
        self.assertIsNone(self.program.required_evaluators)
        response = self.assign([self.solution.pk])
        self.assertEqual(response.status_code, 200, response.data)
        self.program.refresh_from_db()
        self.assertEqual(self.program.required_evaluators, 2)
        self.assertTrue(self.program.is_distributed_evaluation)
        self.assertEqual(SolutionScore.objects.count(), 1)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 1)

    def test_model_guards_program_draft_own_and_existing_assignment_identity(self):
        foreign = create_rate_criteria(self.another_solution(submitted=False).program)
        foreign_program = create_partner_program()
        foreign.partner_program = foreign_program
        foreign.save()
        with self.assertRaises(ValidationError):
            SolutionScore.objects.create(
                solution=self.solution, user=self.expert, criteria=foreign, value="1"
            )
        self.assignment.expert = self.second.expert
        with self.assertRaises(ValidationError):
            self.assignment.save()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionEvaluationRaceTests(EvaluationFixture, TransactionTestCase):
    def setUp(self):
        self.seed_evaluation()

    def race(self, *actions):
        barrier = Barrier(len(actions))

        def run(action):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                action()
                return "ok"
            except SolutionError as error:
                return error.payload["code"]
            except Http404:
                return "not_found"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(actions)) as executor:
            return list(executor.map(run, actions))

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_open_scores_enforce_last_rater_slot(self):
        self.program.required_evaluators = None
        self.program.is_distributed_evaluation = False
        self.program.max_project_rates = 1
        self.program.save()

        def action(actor):
            return lambda: solution_evaluation.rate_solution(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=actor,
                **self.scores(),
            )

        self.assertCountEqual(
            self.race(action(self.expert), action(self.second)),
            ["ok", "max_rates_reached"],
        )
        self.assertEqual(SolutionScore.objects.values("user_id").distinct().count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_score_and_revoke_share_program_lock_without_losing_saved_scores(self):
        expected = self.options()["revision"]
        result = self.race(
            lambda: solution_evaluation.rate_solution(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=self.expert,
                **self.scores(),
            ),
            lambda: solution_assignments.save_assignments(
                program_id=self.program.pk,
                actor=self.manager,
                expert_id=self.expert.expert.pk,
                expected_revision=expected,
                solution_ids=[],
            ),
        )
        self.assertIn("ok", result)
        self.assertTrue(
            "stale_assignments" in result
            or "scores_protected" in result
            or "not_found" in result
        )
        if SolutionScore.objects.exists():
            self.assertTrue(
                SolutionExpertAssignment.objects.filter(
                    solution=self.solution, expert=self.expert.expert
                ).exists()
            )
