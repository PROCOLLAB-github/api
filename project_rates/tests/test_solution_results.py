from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings

from partner_programs.models import (
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
)
from partner_programs.services.results import results_data as project_results
from project_rates.evaluation_math import evaluation_totals, assign_places
from project_rates.models import Criteria, ProjectScore
from project_rates.solution_models import SolutionScore
from project_rates.solution_results import results_data as solution_results
from project_rates.tests.helpers import (
    create_rate_program,
    create_rate_project,
    link_project_to_program,
)
from project_rates.tests.test_solution_evaluation import EvaluationFixture


class EvaluationMathTests(SimpleTestCase):
    def criteria(self):
        return [
            SimpleNamespace(pk=pk, type=kind, min_value=minimum, max_value=maximum)
            for pk, kind, minimum, maximum in [
                (1, "int", 0, 10),
                (2, "float", 0, 20),
                (3, "bool", None, None),
                (4, "str", None, None),
            ]
        ]

    def test_half_up_rounding_complete_only_zero_false_and_comment_null(self):
        result = evaluation_totals(
            self.criteria(),
            {
                1: {1: "0", 2: "1.005", 3: "False", 4: ""},
                2: {1: "0", 2: "1.005", 3: "True", 4: None},
                3: {1: "10", 2: "20", 3: "False"},
            },
        )
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["score"], 1.01)
        self.assertEqual(result["averages"], {"1": 0.0, "2": 1.01})
        self.assertEqual(result["maximum"], 30)
        self.assertFalse(result["evaluations"][3]["complete"])

    def test_invalid_numeric_bool_range_and_partial_values_never_enter_average(self):
        for values in [
            {1: "NaN", 2: "1", 3: "True", 4: ""},
            {1: "1", 2: "Infinity", 3: "True", 4: ""},
            {1: "1.5", 2: "1", 3: "True", 4: ""},
            {1: "11", 2: "1", 3: "True", 4: ""},
            {1: "1", 2: "1", 3: "false", 4: ""},
            {},
        ]:
            with self.subTest(values=values):
                result = evaluation_totals(self.criteria(), {1: values})
                self.assertEqual(result["completed"], 0)
                self.assertIsNone(result["score"])
                self.assertEqual(result["averages"], {})

    def test_no_criteria_or_no_numeric_criteria_have_no_rankable_score(self):
        result = evaluation_totals([], {1: {}})
        self.assertEqual(result["completed"], 0)
        result = evaluation_totals(self.criteria()[2:], {1: {3: "False", 4: ""}})
        self.assertEqual(result["completed"], 1)
        self.assertIsNone(result["score"])
        self.assertFalse(result["has_numeric_criteria"])
        definitions = self.criteria()
        definitions[0].max_value = None
        self.assertIsNone(evaluation_totals(definitions, {})["maximum"])

    def test_ties_use_competition_places_and_incomplete_rows_are_unranked(self):
        rows = [
            dict(solution_id=i, name=str(i), score=value, ready=ready, place=None)
            for i, value, ready in [
                (5, 5, True),
                (3, 3, True),
                (4, 5, True),
                (1, 9, False),
            ]
        ]
        assign_places(rows, "solution_id")
        self.assertEqual(
            {row["solution_id"]: row["place"] for row in rows},
            {5: 1, 3: 3, 4: 1, 1: None},
        )


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionResultsParityTests(EvaluationFixture, TestCase):
    def setUp(self):
        self.seed_evaluation()

    def test_actual_project_and_solution_values_produce_identical_results(self):
        legacy = create_rate_program(is_competitive=True, required_evaluators=2)
        legacy.criterias.all().delete()
        old_criteria = [
            Criteria.objects.create(
                partner_program=legacy,
                name=criterion.name,
                type=criterion.type,
                min_value=criterion.min_value,
                max_value=criterion.max_value,
            )
            for criterion in self.criteria
        ]
        field = PartnerProgramField.objects.create(
            partner_program=legacy,
            name="case",
            field_type="select",
            options="Задача 1",
            label="Кейс",
            is_required=True,
            show_filter=True,
        )
        project = create_rate_project(name=self.solution.name)
        project.name = self.solution.name
        project.save()
        legacy.users.add(project.leader, through_defaults={"partner_program_data": {}})
        link = link_project_to_program(legacy, project)
        PartnerProgramFieldValue.objects.create(
            program_project=link, field=field, value_text="Задача 1"
        )
        PartnerProgramProject.objects.filter(pk=link.pk).update(submitted=True)
        self.program.required_evaluators = 2
        self.program.save()
        for user, number in [(self.expert, "0"), (self.second, "9")]:
            for old, current, value in zip(
                old_criteria, self.criteria, [number, "False", ""]
            ):
                ProjectScore.objects.create(
                    project=project, user=user, criteria=old, value=value
                )
                SolutionScore.objects.create(
                    solution=self.solution, user=user, criteria=current, value=value
                )
        query = dict(search="", case_scope="all", scope="all", order="desc", status="all")
        before = project_results(legacy, query)
        after = solution_results(self.program, query)
        old_row = before["groups"][0]["projects"][0]
        row = after["groups"][0]["solutions"][0]
        for key in [
            "name",
            "case_name",
            "completed",
            "required",
            "evaluation_complete",
            "ready",
            "score",
            "place",
        ]:
            self.assertEqual(row[key], old_row[key], key)
        self.assertEqual(
            list(row["averages"].values()), list(old_row["averages"].values())
        )
        self.assertEqual(row["score"], 4.5)
        self.assertEqual(row["application"]["solution_id"], self.solution.pk)
        self.assertNotIn("project_id", row)
        self.assertEqual(after["maximum"], before["maximum"])
        self.assertEqual(
            [e["total"] for e in row["experts"]], [e["total"] for e in old_row["experts"]]
        )

    def test_filter_keeps_global_place_scope_all_and_projection_does_not_invent_rank(
        self,
    ):
        self.rate()
        query = dict(
            search="missing",
            case_scope="all",
            scope="current",
            order="desc",
            status="all",
        )
        self.assertEqual(solution_results(self.program, query)["groups"], [])
        query["scope"] = "all"
        row = solution_results(self.program, query)["groups"][0]["solutions"][0]
        self.assertEqual(row["place"], 1)
        projection = solution_results(self.program, query, solution_id=self.solution.pk)
        self.assertIsNone(projection["groups"][0]["solutions"][0]["place"])
        self.another_solution(submitted=False)
        self.assertEqual(
            sum(
                len(group["solutions"])
                for group in solution_results(self.program, query)["groups"]
            ),
            1,
        )
