from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from jsonschema import Draft202012Validator

from partner_programs.models import PartnerProgramProject
from partner_programs.services.management_criteria import criteria_data, save_criteria
from partner_programs.services.results import results_data as project_results
from project_rates.criteria_policy import CriteriaConflict
from project_rates.models import Criteria, CriteriaQuerySet, ProjectScore
from project_rates.services import submit_project_scores
from project_rates.solution_models import SolutionScore
from project_rates.solution_results import results_data as solution_results
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)
from project_rates.tests.test_solution_evaluation import EvaluationFixture


def weighted_snapshot(program, manager, weights):
    snapshot = criteria_data(program)
    numbers = iter(weights)
    for row in snapshot["criteria"]:
        row["weight_percent"] = next(numbers) if row["type"] in ("int", "float") else None
    result = save_criteria(
        program.pk,
        manager,
        dict(
            expected_updated_at=snapshot["updated_at"],
            expected_revision=snapshot["revision"],
            scoring_mode="weighted_percent",
            criteria=snapshot["criteria"],
        ),
    )
    program.refresh_from_db()
    return result


class WeightedResultsParityTests(EvaluationFixture, TestCase):
    def test_actual_project_and_solution_scores_share_percentage_ranking_and_contract(
        self,
    ):
        from pathlib import Path
        import json

        self.seed_evaluation()
        self.program.required_evaluators = 2
        self.program.save()
        legacy = create_rate_program(is_competitive=True, required_evaluators=2)
        legacy.managers.add(self.manager)
        legacy.criterias.all().delete()
        old_criteria = [
            Criteria.objects.create(
                partner_program=legacy,
                name=c.name,
                type=c.type,
                min_value=c.min_value,
                max_value=c.max_value,
            )
            for c in self.criteria
        ]
        weighted_snapshot(self.program, self.manager, [100])
        weighted_snapshot(legacy, self.manager, [100])
        project = create_rate_project(name=self.solution.name)
        legacy.users.add(project.leader, through_defaults={"partner_program_data": {}})
        link = link_project_to_program(legacy, project)
        PartnerProgramProject.objects.filter(pk=link.pk).update(submitted=True)
        for user, points in ((self.expert, "8"), (self.second, "6")):
            for old, current, value in zip(
                old_criteria, self.criteria, [points, "False", ""]
            ):
                ProjectScore.objects.create(
                    project=project, user=user, criteria=old, value=value
                )
                SolutionScore.objects.create(
                    solution=self.solution, user=user, criteria=current, value=value
                )
        query = dict(search="", case_scope="all", scope="all", order="desc", status="all")
        before, after = project_results(legacy, query), solution_results(
            self.program, query
        )
        left, right = (
            before["groups"][0]["projects"][0],
            after["groups"][0]["solutions"][0],
        )
        self.assertEqual((left["score"], right["score"]), (70, 70))
        self.assertEqual((before["maximum"], after["maximum"]), (100, 100))
        self.assertEqual((left["place"], right["place"]), (1, 1))
        self.assertEqual(
            list(left["contributions"].values()), list(right["contributions"].values())
        )
        self.assertEqual(list(left["averages"].values()), [7])
        self.assertEqual([e["total"] for e in left["experts"]], [80, 60])
        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text()
        )
        # DateTime JSON serialization follows the actual REST renderer.
        from rest_framework.renderers import JSONRenderer

        Draft202012Validator(
            {
                "components": spec["components"],
                "$ref": "#/components/schemas/SolutionResults",
            }
        ).validate(json.loads(JSONRenderer().render(after)))


class WeightedCriteriaRaceTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    @patch("project_rates.services.send_email.delay")
    def test_percentage_change_and_first_partial_score_are_serialized(self, email):
        program = create_rate_program()
        manager = create_rate_user()
        program.managers.add(manager)
        expert = create_rate_expert(program=program)
        project = create_rate_project()
        link_project_to_program(program, project)
        first = create_rate_criteria(program, min_value=0, max_value=10)
        create_rate_criteria(program, min_value=0, max_value=10)
        snapshot = weighted_snapshot(program, manager, [40, 60])
        payload = dict(
            expected_updated_at=snapshot["updated_at"],
            expected_revision=snapshot["revision"],
            scoring_mode="weighted_percent",
            criteria=snapshot["criteria"],
        )
        for row in payload["criteria"]:
            if row["type"] == "int":
                row["weight_percent"] = 50
        barrier = Barrier(2)

        def run(action):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                if action == "manager":
                    save_criteria(program.pk, manager, payload)
                else:
                    submit_project_scores(
                        user=expert,
                        project_id=project.pk,
                        data={
                            "expected_revision": snapshot["revision"],
                            "scores": [{"criterion_id": first.pk, "value": "8"}],
                        },
                    )
                return "ok"
            except CriteriaConflict:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ["manager", "expert"]))
        self.assertCountEqual(results, ["ok", "conflict"])
        first.refresh_from_db()
        self.assertEqual(
            first.weight_percent, 40 if ProjectScore.objects.exists() else 50
        )


class WeightedModelInterleavingTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_stale_criterion_cannot_move_away_from_a_newly_locked_program(self):
        source = create_rate_program()
        locked_program = create_rate_program()
        target = create_rate_program()
        manager = create_rate_user()
        stale = source.criterias.get(type="str")
        project = create_rate_project()
        link_project_to_program(locked_program, project)
        stale.partner_program = target
        original = CriteriaQuerySet.first
        move = True

        def move_and_score():
            connections.close_all()
            try:
                current = Criteria.objects.get(pk=stale.pk)
                current.partner_program = locked_program
                current.save()
                ProjectScore.objects.create(
                    criteria=current, project=project, user=manager, value="Оценка"
                )
            finally:
                connections.close_all()

        def first(queryset):
            nonlocal move
            old = original(queryset)
            if move and old is not None and old.pk == stale.pk:
                move = False
                # The competing transaction commits before the stale writer locks
                # its originally observed parents; its writes must survive rejection.
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(move_and_score).result(timeout=10)
            return old

        with patch.object(CriteriaQuerySet, "first", first):
            with self.assertRaisesMessage(ValidationError, "Критерий изменился"):
                stale.save()
        stale.refresh_from_db()
        self.assertEqual(stale.partner_program_id, locked_program.pk)
        self.assertTrue(ProjectScore.objects.filter(criteria=stale).exists())
