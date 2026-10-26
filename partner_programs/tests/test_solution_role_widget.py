import json

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject
from partner_programs.solution_models import (
    ProgramSolution,
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
from project_rates.models import Criteria
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.tests.helpers import create_rate_expert
from project_rates.tests.test_solution_evaluation import EvaluationFixture


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionRoleWidgetTests(EvaluationFixture, TestCase):
    def setUp(self):
        self.seed_evaluation()
        self.widget_url = f"/programs/{self.program.pk}/analytics-widget/"

    def widget(self, user=None):
        response = call(user or self.captain, "get", self.widget_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("RoleWidget", response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.data["storage_mode"], "solution")
        self.assertNotIn("participant_project", json.dumps(response.data))
        self.assertNotIn('"scores"', json.dumps(response.data))
        self.assertNotIn('"experts"', json.dumps(response.data))
        return response.data

    def test_participant_reads_own_snapshot_name_case_and_no_live_or_foreign_project(
        self,
    ):
        frozen_name = self.solution.submission_snapshot["name"]
        ProgramSolution.objects.filter(pk=self.solution.pk).update(name="Другое live имя")
        self.program.fields.filter(name="case").update(
            name="retired_case", purpose="other"
        )
        data = self.widget()["participant"]
        self.assertEqual(
            data["application"],
            dict(
                kind="solution",
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                name=frozen_name,
            ),
        )
        self.assertTrue(data["case_provided"])
        self.assertEqual(data["case_name"], "Задача 1")
        self.assertEqual(data["stage"], "review")

    def test_accepted_members_share_application_and_pending_is_not_membership(self):
        draft = self.another_solution(submitted=False)
        member, pending = create_user(), create_user()
        for user in [member, pending]:
            create_program_member(self.program, user=user)
        ProgramSolutionMember.objects.create(
            solution=draft, user=member, role="Разработчик"
        )
        SolutionInvitation.objects.create(
            solution=draft, recipient=pending, role="Дизайнер"
        )
        leader = self.widget(draft.captain)["participant"]
        self.assertEqual(self.widget(member)["participant"], leader)
        self.assertEqual(leader["application"]["solution_id"], draft.pk)
        self.assertIsNone(leader["case_name"])
        self.assertEqual(leader["stage"], "not_submitted")
        self.assertIsNone(self.widget(pending)["participant"]["application"])

    def test_organizer_counts_solutions_and_distinct_accepted_team_not_project_or_pending(
        self,
    ):
        draft = self.another_solution(submitted=False)
        member, pending, legacy_only = [create_user() for _ in range(3)]
        for user in [member, pending, legacy_only]:
            create_program_member(self.program, user=user)
        ProgramSolutionMember.objects.create(solution=draft, user=member)
        SolutionInvitation.objects.create(solution=draft, recipient=pending, role="Роль")
        # Historical linkage is deliberately present; it is not a solution team.
        project = create_project(leader=legacy_only)
        PartnerProgramProject.objects.bulk_create(
            [PartnerProgramProject(partner_program=self.program, project=project)]
        )
        data = self.widget(self.manager)["organizer"]
        self.assertEqual(
            data,
            dict(
                participants=5,
                solutions=2,
                submitted_solutions=1,
                participants_without_solution=2,
            ),
        )
        self.assertNotIn("projects", data)

    def test_expert_counts_own_complete_zero_false_and_unchanged_fact_after_deadline(
        self,
    ):
        self.assertNotEqual(self.expert.pk, self.expert.expert.pk)
        self.assertEqual(self.widget(self.expert)["expert"]["remaining"], 1)
        response = self.rate()
        self.assertEqual(response.status_code, 200, response.data)
        self.program.datetime_evaluation_ends = timezone.now() - timezone.timedelta(
            hours=1
        )
        self.program.save(update_fields=["datetime_evaluation_ends"])
        data = self.widget(self.expert)["expert"]
        self.assertEqual(data["assigned"], 1)
        self.assertEqual(data["remaining"], 0)
        self.assertIsNotNone(data["evaluation_ends"])
        self.assertEqual(self.widget()["participant"]["stage"], "evaluated")

    def test_other_expert_scores_do_not_complete_personal_work_or_required_quota(self):
        self.program.required_evaluators = 2
        self.program.save(update_fields=["required_evaluators"])
        SolutionExpertAssignment.objects.create(
            partner_program=self.program,
            solution=self.solution,
            expert=self.second.expert,
        )
        self.assertEqual(self.rate().status_code, 200)
        self.assertEqual(self.widget(self.expert)["expert"]["remaining"], 0)
        self.assertEqual(self.widget(self.second)["expert"]["remaining"], 1)
        self.assertEqual(self.widget()["participant"]["stage"], "review")
        self.assertEqual(self.rate(actor=self.second).status_code, 200)
        self.assertEqual(self.widget()["participant"]["stage"], "evaluated")

    def test_draft_not_ready_assignment_stays_in_expert_remaining(self):
        draft = self.another_solution(submitted=False)
        # Supported writes reject not-ready work; this models a historical row.
        SolutionExpertAssignment.objects.bulk_create(
            [
                SolutionExpertAssignment(
                    partner_program=self.program,
                    solution=draft,
                    expert=self.expert.expert,
                )
            ]
        )
        self.assertEqual(self.rate().status_code, 200)
        data = self.widget(self.expert)["expert"]
        self.assertEqual((data["assigned"], data["remaining"]), (2, 1))

    def test_open_stage_uses_existing_first_score_rule_with_inapplicable_personal_counts(
        self,
    ):
        self.program.is_distributed_evaluation = False
        self.program.save(update_fields=["is_distributed_evaluation"])
        self.assertEqual(self.widget()["participant"]["stage"], "submitted")
        SolutionScore.objects.create(
            solution=self.solution, user=self.expert, criteria=self.criteria[0], value="0"
        )
        self.assertEqual(self.widget()["participant"]["stage"], "evaluated")
        data = self.widget(self.expert)["expert"]
        self.assertEqual(data["mode"], "open")
        self.assertIsNone(data["assigned"])
        self.assertIsNone(data["remaining"])

    def test_noncompetitive_saved_solution_does_not_require_submission(self):
        self.program.is_competitive = False
        self.program.save(update_fields=["is_competitive"])
        draft = self.another_solution(submitted=False)
        self.assertEqual(
            self.widget(draft.captain)["participant"]["stage"], "not_applicable"
        )
        self.assertIsNone(self.widget(self.manager)["organizer"]["submitted_solutions"])
        self.assertIsNone(self.widget(self.expert)["expert"]["assigned"])
        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")

    def test_no_criteria_never_completes_a_submitted_assignment(self):
        Criteria.objects.filter(partner_program=self.program).delete()
        data = self.widget(self.expert)["expert"]
        self.assertEqual((data["assigned"], data["remaining"]), (1, 1))
        self.assertEqual(self.widget()["participant"]["stage"], "review")

    def test_ambiguous_owned_solutions_return_existing_409_detail_without_first_match(
        self,
    ):
        draft = self.another_solution(submitted=False)
        ProgramSolutionMember.objects.bulk_create(
            [ProgramSolutionMember(solution=draft, user=self.captain)]
        )
        response = call(self.captain, "get", self.widget_url)
        self.assertEqual(response.status_code, 409)
        self.assert_schema("WidgetError", response.data)
        self.assertEqual(set(response.data), {"detail"})

    def test_role_priority_scope_and_client_claims_do_not_reveal_other_work(self):
        create_program_member(self.program, user=self.expert)
        self.assertEqual(self.widget(self.expert)["role"], "expert")
        self.program.managers.add(self.expert)
        self.assertEqual(self.widget(self.expert)["role"], "organizer")
        outsider = create_user(is_staff=True)
        response = call(
            outsider,
            "get",
            self.widget_url
            + f"?role=organizer&user_id={self.captain.pk}&solution_id={self.solution.pk}",
        )
        self.assertEqual(response.status_code, 403)
        self.assert_schema("WidgetError", response.data)
        self.assertEqual(APIClient().get(self.widget_url).status_code, 401)

    def test_foreign_assignments_and_expert_identity_do_not_change_own_widget(self):
        from partner_programs.tests.test_solution_foundation import solution_program
        from partner_programs.solution_api import create_solution

        other = solution_program(is_competitive=True)
        owner = create_user()
        create_program_member(other, user=owner)
        solution, _ = create_solution(other.pk, owner, {})
        foreign = create_rate_expert(program=other)
        self.expert.expert.programs.add(other)
        SolutionExpertAssignment.objects.bulk_create(
            [
                SolutionExpertAssignment(
                    partner_program=other, solution=solution, expert=self.expert.expert
                ),
                SolutionExpertAssignment(
                    partner_program=self.program,
                    solution=self.solution,
                    expert=foreign.expert,
                ),
            ]
        )
        self.assertEqual(self.widget(self.expert)["expert"]["assigned"], 1)
        response = call(foreign, "get", self.widget_url + f"?user_id={self.expert.pk}")
        self.assertEqual(response.status_code, 403)
        self.assert_schema("WidgetError", response.data)

    def test_legacy_reference_is_not_recast_to_a_solution_when_program_mode_changed(self):
        user = create_user()
        create_program_member(self.program, user=user)
        project = create_project(leader=user)
        PartnerProgramProject.objects.bulk_create(
            [PartnerProgramProject(partner_program=self.program, project=project)]
        )
        response = call(user, "get", self.widget_url)
        self.assertEqual(response.status_code, 409)
        self.assert_schema("WidgetError", response.data)
        self.assertNotIn("application", response.data)

    def test_legacy_widget_keeps_its_body_shape_and_matches_the_shared_contract(self):
        legacy = create_partner_program(is_competitive=True)
        create_program_member(legacy, user=self.captain)
        project = create_project(leader=self.captain)
        link = PartnerProgramProject.objects.create(
            partner_program=legacy, project=project
        )
        response = call(self.captain, "get", f"/programs/{legacy.pk}/analytics-widget/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_schema("RoleWidget", response.data)
        self.assertEqual(
            set(response.data), {"program_id", "role", "is_competitive", "participant"}
        )
        self.assertEqual(
            response.data["participant"]["participant_project"],
            {"id": project.pk, "name": project.name, "program_link_id": link.pk},
        )

    def test_query_count_is_constant_and_get_has_no_business_writes_for_each_role(self):
        users = [self.manager, self.expert, self.captain]
        counts = []
        for user in users:
            with CaptureQueriesContext(connection) as queries:
                self.widget(user)
            counts.append(len(queries))
            self.assertLessEqual(len(queries), 14)
            self.assertFalse(
                any(
                    row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                    for row in queries
                )
            )
        for _ in range(8):
            solution = self.another_solution()
            SolutionExpertAssignment.objects.create(
                partner_program=self.program, solution=solution, expert=self.expert.expert
            )
        for user, expected in zip(users, counts):
            with CaptureQueriesContext(connection) as queries:
                self.widget(user)
            self.assertEqual(len(queries), expected)
