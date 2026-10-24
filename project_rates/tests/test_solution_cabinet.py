from django.test import TestCase, override_settings

from partner_programs.tests.test_solution_forms import call
from project_rates.models import ProjectExpertAssignment
from project_rates.solution_models import SolutionExpertAssignment
from project_rates.tests.helpers import (
    create_rate_program,
    create_rate_project,
    link_project_to_program,
)
from project_rates.tests.test_solution_evaluation import EvaluationFixture


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionCabinetTests(EvaluationFixture, TestCase):
    def setUp(self):
        self.seed_evaluation()
        self.legacy = create_rate_program(
            is_competitive=True, required_evaluators=1, is_distributed_evaluation=True
        )
        self.expert.expert.programs.add(self.legacy)
        self.project = create_rate_project(name="Другая работа")
        self.legacy.users.add(
            self.project.leader, through_defaults={"partner_program_data": {}}
        )
        self.link = link_project_to_program(self.legacy, self.project)
        self.link.submitted = True
        self.link.save()
        self.legacy_assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.legacy, project=self.project, expert=self.expert.expert
        )
        self.cabinet_url = "/evaluation/applications/"

    def page(self, query="", actor=None):
        response = call(actor or self.expert, "get", self.cabinet_url + query)
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("CabinetApplications", response.data)
        return response.data

    def test_mixed_ids_are_discriminated_and_single_pagination_follows_global_count(self):
        page = self.page("?limit=1")
        other = self.page("?limit=1&offset=1")
        self.assertEqual(page["count"], 2)
        self.assertEqual(page["pending"], 2)
        rows = page["results"] + other["results"]
        self.assertEqual(
            {row["application"]["kind"] for row in rows}, {"solution", "legacy_project"}
        )
        legacy = next(
            row for row in rows if row["application"]["kind"] == "legacy_project"
        )
        solution = next(row for row in rows if row["application"]["kind"] == "solution")
        self.assertEqual(legacy["application"]["project_id"], self.project.pk)
        self.assertEqual(solution["application"]["solution_id"], self.solution.pk)
        self.assertEqual(legacy["application"]["program_link_id"], self.link.pk)
        self.assertNotIn("project_id", solution["application"])
        self.assertEqual(self.page("?offset=100")["results"], [])

    def test_completion_search_and_program_filter_preserve_global_tabs_counts(self):
        self.rate()
        completed = self.page("?status=completed")
        self.assertEqual(completed["count"], 1)
        self.assertEqual(completed["completed"], 1)
        self.assertEqual(completed["pending"], 1)
        self.assertEqual(completed["results"][0]["application"]["kind"], "solution")
        self.assertEqual(self.page(f"?program_id={self.legacy.pk}")["count"], 1)
        missing = self.page("?q=no-match")
        self.assertEqual(missing["count"], 0)
        self.assertEqual(missing["pending"], 1)

    def test_actual_membership_and_assignment_scope_hide_foreign_work(self):
        self.assertEqual(self.page(actor=self.second)["count"], 0)
        self.program.experts.remove(self.expert.expert)
        page = self.page()
        self.assertEqual(page["count"], 1)
        self.assertEqual(page["results"][0]["application"]["kind"], "legacy_project")
        self.assertEqual(self.page(actor=self.captain)["count"], 0)

    def test_old_programs_and_include_projects_contract_stay_unchanged(self):
        old = call(self.expert, "get", "/evaluation/programs/").data
        self.assertEqual(set(old), {"results", "has_access"})
        own = next(row for row in old["results"] if row["id"] == self.program.pk)
        self.assertEqual(own["assigned"], 1)
        self.assertEqual(own["remaining"], 1)
        included = call(self.expert, "get", "/evaluation/programs/?include=projects").data
        self.assertEqual(set(included), {"results", "has_access", "projects"})
        self.assertEqual(included["projects"]["count"], 1)
        self.assertIn("project_id", included["projects"]["results"][0])

    def test_unavailable_draft_is_counted_without_exposing_it(self):
        draft = self.another_solution(submitted=False)
        SolutionExpertAssignment.objects.bulk_create(
            [
                SolutionExpertAssignment(
                    partner_program=self.program,
                    solution=draft,
                    expert=self.expert.expert,
                )
            ]
        )
        page = self.page()
        self.assertEqual(page["count"], 2)
        self.assertEqual(page["unavailable"], 1)
        self.assertFalse(
            any(
                row["application"].get("solution_id") == draft.pk
                for row in page["results"]
            )
        )

    def test_query_is_strict_and_private(self):
        for query in [
            "?limit=0",
            "?offset=-1",
            "?program_id=0",
            "?solution_id=1",
            "?status=all",
        ]:
            self.assertEqual(
                call(self.expert, "get", self.cabinet_url + query).status_code, 400
            )
        response = call(self.expert, "get", self.cabinet_url)
        self.assertEqual(response["Cache-Control"], "private, no-store")
