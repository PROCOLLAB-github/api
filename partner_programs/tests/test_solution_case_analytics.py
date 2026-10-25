from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_project,
    create_user,
)
from partner_programs.tests.test_solution_forms import call
from project_rates.tests.test_solution_evaluation import EvaluationFixture


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionCaseAnalyticsTests(EvaluationFixture, TestCase):
    def setUp(self):
        self.seed_evaluation()
        self.case = self.program.fields.get(pk=self.fields["select"]["id"])
        self.analytics_url = f"/programs/{self.program.pk}/management/solution-cases/"

    def analytics(self, actor=None):
        response = call(actor or self.manager, "get", self.analytics_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("CaseSolutionAnalytics", response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        return response.data

    def choose(self, solution, value):
        # Historical/empty values are read safely, even if supported writes reject them.
        ProgramSolutionAnswer.objects.bulk_create(
            [ProgramSolutionAnswer(solution=solution, field=self.case, value=value)]
        )

    def test_real_solutions_current_option_order_zero_rows_and_without_case(self):
        valid = self.another_solution(submitted=False)
        self.choose(valid, self.case.get_options_list()[0])
        for value in ["", "Устаревший кейс"]:
            self.choose(self.another_solution(submitted=False), value)
        self.another_solution(submitted=False)
        result = self.analytics()
        self.assertEqual(
            [item["name"] for item in result["items"]], self.case.get_options_list()
        )
        first = result["items"][0]
        self.assertEqual(
            [first[key] for key in ("solutions_total", "submitted", "not_submitted")],
            [2, 1, 1],
        )
        self.assertTrue(all(row["solutions_total"] == 0 for row in result["items"][1:]))
        self.assertEqual(result["without_case"]["solutions_total"], 3)
        self.assertEqual(
            sum(row["solutions_total"] for row in result["items"])
            + result["without_case"]["solutions_total"],
            self.program.solutions.count(),
        )

    def test_submitted_snapshot_ignores_changed_live_answers_captain_and_members(self):
        initial = self.analytics()["items"][0]
        user = create_user()
        create_program_member(self.program, user=user)
        ProgramSolution.objects.filter(pk=self.solution.pk).update(captain=user)
        ProgramSolutionAnswer.objects.filter(
            solution=self.solution, field=self.case
        ).update(value="Устаревший кейс")
        ProgramSolutionMember.objects.bulk_create(
            [ProgramSolutionMember(solution=self.solution, user=user)]
        )
        self.assertEqual(self.analytics()["items"][0], initial)
        self.assertEqual(initial["participants_total"], 1)

    def test_accepted_registered_teams_not_pending_unregistered_or_legacy(self):
        draft = self.another_solution(submitted=False)
        self.choose(draft, "Задача 1")
        member, pending, unregistered = [create_user() for _ in range(3)]
        create_program_member(self.program, user=member)
        create_program_member(self.program, user=pending)
        ProgramSolutionMember.objects.create(solution=draft, user=member)
        ProgramSolutionMember.objects.create(solution=draft, user=unregistered)
        SolutionInvitation.objects.create(solution=draft, recipient=pending, role="Роль")
        project = create_project(leader=pending)
        PartnerProgramProject.objects.bulk_create(
            [PartnerProgramProject(partner_program=self.program, project=project)]
        )
        item = self.analytics()["items"][0]
        self.assertEqual(item["participants_total"], 3)
        self.assertEqual(item["solutions_total"], 2)

    def test_same_registered_person_is_unique_within_bucket_not_across_cases(self):
        self.case.solution_options = [*self.case.get_options_list(), "Задача 2"]
        self.case.save(update_fields=["solution_options"])
        person = create_user()
        create_program_member(self.program, user=person)
        for case in ["Задача 1", "Задача 1", "Задача 2"]:
            draft = self.another_solution(submitted=False)
            self.choose(draft, case)
            # Historical duplicate memberships must not inflate a bucket.
            ProgramSolutionMember.objects.bulk_create(
                [ProgramSolutionMember(solution=draft, user=person)]
            )
        items = {row["name"]: row for row in self.analytics()["items"]}
        self.assertEqual(items["Задача 1"]["participants_total"], 4)
        self.assertEqual(items["Задача 2"]["participants_total"], 2)

    def test_noncompetitive_preserves_draft_without_artificial_submission(self):
        self.program.is_competitive = False
        self.program.save(update_fields=["is_competitive"])
        draft = self.another_solution(submitted=False)
        result = self.analytics()
        self.assertFalse(result["submission_applicable"])
        for row in [*result["items"], result["without_case"]]:
            self.assertIsNone(row["submitted"])
            self.assertIsNone(row["not_submitted"])
        self.assertEqual(result["without_case"]["solutions_total"], 1)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")

    def test_unconfigured_case_and_missing_current_options_are_without_case(self):
        self.program.fields.filter(pk=self.case.pk).update(name="retired_case")
        result = self.analytics()
        self.assertFalse(result["configured"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["without_case"]["solutions_total"], 1)
        self.assertEqual(result["without_case"]["participants_total"], 1)

    def test_another_program_of_same_captain_does_not_change_case_aggregates(self):
        from partner_programs.solution_api import create_solution
        from partner_programs.tests.test_solution_foundation import solution_program

        before = self.analytics()
        other = solution_program(is_competitive=True)
        create_program_member(other, user=self.captain)
        foreign, _ = create_solution(other.pk, self.captain, {})
        self.assertNotEqual(foreign.program_id, self.program.pk)
        self.assertEqual(self.analytics(), before)

    def test_scope_and_errors_never_grant_participant_or_expert_manager_data(self):
        for user in [self.captain, self.expert, create_user()]:
            response = call(user, "get", self.analytics_url)
            self.assertEqual(response.status_code, 403)
            self.assert_schema("Error", response.data)
        response = APIClient().get(self.analytics_url)
        self.assertEqual(response.status_code, 401)
        self.assert_schema("Error", response.data)
        self.assertEqual(
            call(self.manager, "get", self.analytics_url + "?user_id=1").status_code,
            400,
        )
        other = create_partner_program()
        url = f"/programs/{other.pk}/management/solution-cases/"
        self.assertEqual(call(self.manager, "get", url).status_code, 403)
        other.managers.add(self.manager)
        response = call(self.manager, "get", url)
        self.assertEqual(response.status_code, 409)
        self.assert_schema("Error", response.data)
        self.assertEqual(response.data["code"], "solution_mode_unavailable")
        self.assertEqual(
            call(
                self.manager, "get", "/programs/90000000/management/solution-cases/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.analytics(create_user(is_staff=True))["program_id"], self.program.pk
        )

    def test_bounded_queries_read_only_and_no_private_payload(self):
        with CaptureQueriesContext(connection) as before:
            result = self.analytics()
        self.assertLessEqual(len(before), 10)
        for _ in range(8):
            self.another_solution(submitted=False)
        with CaptureQueriesContext(connection) as after:
            self.analytics()
        self.assertEqual(len(before), len(after))
        self.assertFalse(
            any(
                row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for row in after
            )
        )
        self.assertEqual(
            set(result),
            {
                "program_id",
                "configured",
                "submission_applicable",
                "items",
                "without_case",
            },
        )
        self.assertFalse(ProgramSolution.objects.exclude(program=self.program).exists())
