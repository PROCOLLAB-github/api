"""Контракт Angular-виджета: права, общие расчёты и отсутствие побочных записей."""

from django.db import connection, IntegrityError, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramFieldValue
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator


class ProgramRoleWidgetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.program = create_partner_program(
            is_competitive=True, is_distributed_evaluation=True, max_project_rates=3
        )
        self.member = create_user()
        create_program_member(self.program, user=self.member)
        self.url = reverse(
            "partner_programs:analytics-widget", kwargs={"pk": self.program.pk}
        )
        self.client.force_authenticate(self.member)

    def widget(self, user=None):
        if user is not None:
            self.client.force_authenticate(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_program_roles_and_priority_without_assignments(self):
        expert = create_rate_expert(program=self.program)
        self.assertEqual(self.widget(expert)["role"], "expert")
        self.assertEqual(self.widget()["expert"]["assigned"], 0)
        create_program_member(self.program, user=expert)
        self.assertEqual(self.widget()["role"], "expert")
        self.program.managers.add(expert)
        data = self.widget()
        self.assertEqual(data["role"], "organizer")
        self.assertNotIn("expert", data)
        self.assertNotIn("participant", data)

    def test_outsider_other_program_staff_and_client_claims_do_not_grant_role(self):
        other = create_partner_program()
        for user in (
            create_user(),
            create_rate_expert(program=other),
            create_user(is_staff=True),
        ):
            self.client.force_authenticate(user)
            response = self.client.get(
                self.url, {"role": "organizer", "user_id": self.member.pk}
            )
            self.assertEqual(response.status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_member_and_expert_cannot_access_manager_api(self):
        url = reverse(
            "partner_programs:project-analytics", kwargs={"program_id": self.program.pk}
        )
        for user in (self.member, create_rate_expert(program=self.program)):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_no_project_and_case_not_configured(self):
        data = self.widget()["participant"]
        self.assertIsNone(data["participant_project"])
        self.assertEqual(data["stage"], "none")
        self.assertFalse(data["case_provided"])

    def test_leader_and_collaborator_see_identical_program_scoped_project(self):
        teammate = create_user()
        create_program_member(self.program, user=teammate)
        project = create_project(leader=self.member)
        Collaborator.objects.create(project=project, user=teammate, role="Participant")
        link = create_program_project(self.program, project=project)
        other = create_partner_program()
        other_link = create_program_project(other, project=project, submitted=True)
        for program, program_link, value in (
            (self.program, link, "Alpha"),
            (other, other_link, "Beta"),
        ):
            field = create_program_field(
                program,
                name="case",
                field_type="select",
                is_required=True,
                show_filter=True,
                options=[value],
            )
            PartnerProgramFieldValue.objects.create(
                program_project=program_link, field=field, value_text=value
            )
        leader_data = self.widget()["participant"]
        team_data = self.widget(teammate)["participant"]
        self.assertEqual(leader_data, team_data)
        self.assertEqual(team_data["participant_project"]["program_link_id"], link.pk)
        self.assertEqual(team_data["case_name"], "Alpha")
        self.assertEqual(team_data["stage"], "not_submitted")
        fields_url = f"/programs/partner-program-projects/{link.pk}/fields/"
        self.assertEqual(self.client.get(fields_url).status_code, 200)
        self.assertEqual(self.client.put(fields_url, [], format="json").status_code, 403)
        submit_url = f"/programs/partner-program-projects/{link.pk}/submit/"
        self.assertEqual(self.client.post(submit_url).status_code, 403)
        self.assertEqual(self.client.get(f"/projects/{project.pk}/").status_code, 200)
        # Существующий PROD-контракт заявки остаётся доступен только лидеру.
        detail = self.client.get(f"/programs/{self.program.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("current_application", detail.data)
        self.assertIsNone(detail.data["current_project_application"])
        self.client.force_authenticate(self.member)
        detail = self.client.get(f"/programs/{self.program.pk}/")
        self.assertEqual(
            detail.data["current_project_application"]["program_link_id"], link.pk
        )

    def test_integrity_conflict_does_not_choose_first_project(self):
        for _ in range(2):
            create_program_project(
                self.program, project=create_project(leader=self.member)
            )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("participant", response.data)

    def test_case_uses_exact_name_and_never_defaults_to_first_option(self):
        create_program_project(self.program, project=create_project(leader=self.member))
        create_program_field(self.program, name="topic", label="Кейс")
        self.assertFalse(self.widget()["participant"]["case_provided"])
        create_program_field(
            self.program,
            name="case",
            label="Challenge",
            field_type="select",
            is_required=True,
            show_filter=True,
            options=["Alpha"],
        )
        data = self.widget()["participant"]
        self.assertTrue(data["case_provided"])
        self.assertIsNone(data["case_name"])

    def test_distributed_stages_zero_partial_complete_and_not_ready(self):
        project = create_project(leader=self.member)
        link = create_program_project(self.program, project=project, submitted=True)
        self.assertEqual(self.widget()["participant"]["stage"], "submitted")
        # Программа создаёт критерий «Комментарий»; здесь изолируем два явных критерия.
        self.program.criterias.all().delete()
        criteria = [
            Criteria.objects.create(
                name=f"C{i}",
                type="int",
                min_value=0,
                max_value=10,
                partner_program=self.program,
            )
            for i in range(2)
        ]
        experts = [create_rate_expert(program=self.program) for _ in range(2)]
        for expert in experts:
            ProjectExpertAssignment.objects.create(
                partner_program=self.program, project=project, expert=expert.expert
            )
        self.assertEqual(self.widget()["participant"]["stage"], "review")
        for criterion in criteria:
            ProjectScore.objects.create(
                project=project, user=experts[0], criteria=criterion, value="0"
            )
        self.assertEqual(self.widget()["participant"]["stage"], "review")
        self.assertEqual(self.widget(experts[0])["expert"]["remaining"], 0)
        ProjectScore.objects.create(
            project=project, user=experts[1], criteria=criteria[0], value="0"
        )
        self.assertEqual(self.widget(experts[1])["expert"]["remaining"], 1)
        ProjectScore.objects.create(
            project=project, user=experts[1], criteria=criteria[1], value="0"
        )
        self.assertEqual(self.widget(self.member)["participant"]["stage"], "evaluated")
        link.submitted = False
        link.save(update_fields=["submitted"])
        self.assertEqual(self.widget(experts[0])["expert"]["remaining"], 1)
        self.assertEqual(
            self.widget(self.member)["participant"]["stage"], "not_submitted"
        )

    def test_open_mode_uses_existing_project_completion_without_invented_assignments(
        self,
    ):
        self.program.is_distributed_evaluation = False
        self.program.save(update_fields=["is_distributed_evaluation"])
        expert = create_rate_expert(program=self.program)
        project = create_project(leader=self.member)
        create_program_project(self.program, project=project, submitted=True)
        criterion = Criteria.objects.create(
            name="C", type="int", partner_program=self.program
        )
        ProjectScore.objects.create(
            project=project, criteria=criterion, user=expert, value="0"
        )
        self.assertEqual(self.widget()["participant"]["stage"], "evaluated")
        data = self.widget(expert)["expert"]
        self.assertEqual(data["mode"], "open")
        self.assertIsNone(data["assigned"])
        self.assertIsNone(data["remaining"])

    def test_manager_metrics_match_overview_including_draft_team_and_other_program(self):
        manager = create_user()
        self.program.managers.add(manager)
        teammate = create_user()
        create_program_member(self.program, user=teammate)
        project = create_project(leader=self.member, draft=True)
        create_program_project(self.program, project=project)
        Collaborator.objects.create(project=project, user=teammate, role="Participant")
        without_project = create_user()
        create_program_member(self.program, user=without_project)
        create_program_project(
            create_partner_program(), project=create_project(leader=without_project)
        )
        data = self.widget(manager)["organizer"]
        overview = self.client.get(
            reverse(
                "partner_programs:project-analytics", kwargs={"program_id": self.program.pk}
            )
        ).data
        self.assertEqual(data["participants"], 3)
        self.assertEqual(data["projects"], 1)
        self.assertEqual(data["participants_without_project"], 1)
        self.assertEqual(
            data["participants"], overview["summary"]["participants"]["total"]
        )
        self.assertEqual(data["projects"], overview["summary"]["projects"]["total"])
        self.assertEqual(
            data["submitted_solutions"], overview["solution_funnel"]["submitted"]
        )
        self.assertEqual(
            data["participants_without_project"],
            overview["attention"]["participants_without_team"],
        )

    def test_noncompetitive_metrics_are_inapplicable(self):
        self.program.is_competitive = False
        self.program.save(update_fields=["is_competitive"])
        self.assertEqual(self.widget()["participant"]["stage"], "not_applicable")
        self.program.managers.add(self.member)
        self.assertIsNone(self.widget()["organizer"]["submitted_solutions"])

    def test_get_has_bounded_queries_and_no_business_writes(self):
        self.program.managers.add(self.member)
        with CaptureQueriesContext(connection) as queries:
            self.widget()
        self.assertLessEqual(len(queries), 5)
        self.assertFalse(
            any(
                q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for q in queries
            )
        )
        for _ in range(12):
            create_program_project(self.program)
        with CaptureQueriesContext(connection) as larger_queries:
            self.widget()
        self.assertEqual(len(queries), len(larger_queries))

    def test_duplicate_registration_is_rejected_and_users_are_counted_once(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_program_member(self.program, user=self.member)
        self.program.managers.add(self.member)
        self.assertEqual(self.widget()["organizer"]["participants"], 1)

    def test_expert_flag_does_not_expose_member_only_detail(self):
        expert = create_rate_expert(program=self.program)
        self.client.force_authenticate(expert)
        response = self.client.get(f"/programs/{self.program.pk}/")
        self.assertTrue(response.data["is_user_expert"])
        self.assertFalse(response.data["is_user_member"])
        self.assertNotIn("description", response.data)
        self.assertNotIn("links", response.data)

    def test_other_program_assignment_and_submission_deadline_are_not_used(self):
        from django.utils import timezone

        self.program.datetime_evaluation_ends = timezone.now() - timezone.timedelta(
            hours=1
        )
        self.program.save(update_fields=["datetime_evaluation_ends"])
        other = create_partner_program()
        expert = create_rate_expert(program=self.program)
        expert.expert.programs.add(other)
        link = create_program_project(other, submitted=True)
        ProjectExpertAssignment.objects.create(
            partner_program=other, project=link.project, expert=expert.expert
        )
        data = self.widget(expert)["expert"]
        self.assertEqual(data["assigned"], 0)
        self.assertEqual(data["remaining"], 0)
        self.assertIsNotNone(data["evaluation_ends"])
