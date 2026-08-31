from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramUserProfile
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator


class ProgramManagerAnalyticsAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = create_user(prefix="analytics-manager")
        self.program = create_partner_program()
        self.program.managers.add(self.manager)
        self.url = reverse(
            "partner_programs:manager-overview",
            kwargs={"pk": self.program.id},
        )

    def test_manager_can_open_analytics(self):
        self.client.force_authenticate(self.manager)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_staff_and_superuser_can_open_analytics(self):
        for user in (
            create_user(prefix="analytics-staff", is_staff=True),
            create_user(prefix="analytics-superuser", is_superuser=True),
        ):
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)

    def test_participant_cannot_open_analytics(self):
        participant = create_user(prefix="analytics-participant")
        create_program_member(self.program, user=participant)
        self.client.force_authenticate(participant)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_open_analytics(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_missing_program_returns_not_found(self):
        staff = create_user(prefix="analytics-missing-staff", is_staff=True)
        self.client.force_authenticate(staff)

        response = self.client.get(
            reverse("partner_programs:manager-overview", kwargs={"pk": 999999})
        )

        self.assertEqual(response.status_code, 404)


class ProgramManagerAnalyticsMetricsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = create_user(prefix="analytics-metrics-manager")
        self.program = create_partner_program(max_project_rates=2)
        self.program.managers.add(self.manager)
        self.client.force_authenticate(self.manager)
        self.url = reverse(
            "partner_programs:manager-overview",
            kwargs={"pk": self.program.id},
        )

    def test_summary_participant_funnel_and_regions_use_real_relations(self):
        leader = create_user(prefix="analytics-leader")
        collaborator = create_user(prefix="analytics-collaborator")
        participant_without_team = create_user(prefix="analytics-no-team")
        for user in (leader, collaborator, participant_without_team):
            create_program_member(self.program, user=user)
        PartnerProgramUserProfile.objects.create(
            user=None,
            partner_program=self.program,
            partner_program_data={},
        )

        project = create_project(leader=leader, region=" Moscow ")
        create_program_project(self.program, project=project, submitted=True)
        Collaborator.objects.create(user=collaborator, project=project)
        second_project = create_project(region="Moscow")
        create_program_project(self.program, project=second_project)

        first_expert = create_rate_expert(
            prefix="analytics-summary-expert-1",
            program=self.program,
        )
        second_expert = create_rate_expert(
            prefix="analytics-summary-expert-2",
            program=self.program,
        )
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=project,
            expert=first_expert.expert,
        )
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=second_project,
            expert=first_expert.expert,
        )
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=project,
            expert=second_expert.expert,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["summary"],
            {
                "participants": {"total": 3},
                "projects": {"total": 2},
                "experts": {"total": 2},
                "regions": {
                    "total": 1,
                    "items": [{"name": "Moscow", "count": 2}],
                },
            },
        )
        self.assertEqual(
            response.data["participant_funnel"],
            {
                "registrations": 4,
                "unique_participants": 3,
                "with_team": 2,
                "project_creators": 1,
                "submitted_project_creators": 1,
            },
        )
        self.assertEqual(response.data["attention"]["participants_without_team"], 1)

    def test_open_evaluation_uses_any_score_instead_of_max_project_rates(self):
        evaluated_project = create_project(name="Evaluated")
        partial_project = create_project(name="Partially evaluated")
        pending_project = create_project(name="Pending")
        draft_solution = create_project(name="Not submitted")
        for project, submitted in (
            (evaluated_project, True),
            (partial_project, True),
            (pending_project, True),
            (draft_solution, False),
        ):
            create_program_project(
                self.program,
                project=project,
                submitted=submitted,
            )

        first_expert = create_rate_expert(
            prefix="analytics-evaluation-expert-1",
            program=self.program,
        )
        second_expert = create_rate_expert(
            prefix="analytics-evaluation-expert-2",
            program=self.program,
        )
        for project, expert in (
            (evaluated_project, first_expert),
            (evaluated_project, second_expert),
            (partial_project, first_expert),
            (partial_project, second_expert),
            (pending_project, first_expert),
        ):
            ProjectExpertAssignment.objects.create(
                partner_program=self.program,
                project=project,
                expert=expert.expert,
            )

        criteria = Criteria.objects.create(
            name="Impact",
            type="int",
            min_value=0,
            max_value=10,
            partner_program=self.program,
        )
        for project, expert in (
            (evaluated_project, first_expert),
            (evaluated_project, second_expert),
            (partial_project, first_expert),
        ):
            ProjectScore.objects.create(
                criteria=criteria,
                user=expert,
                project=project,
                value="8",
            )

        response = self.client.get(self.url)

        self.assertEqual(
            response.data["solution_funnel"],
            {
                "created": 4,
                "not_submitted": 1,
                "submitted": 3,
                "evaluated": 2,
            },
        )
        self.assertEqual(
            response.data["evaluation_status"],
            {
                "mode": "open",
                "max_evaluations_per_project": 2,
                "assignments": {"total": 5, "pending": 2, "evaluated": 3},
                "projects": {
                    "submitted": 3,
                    "awaiting_evaluation": 1,
                    "partially_evaluated": 0,
                    "evaluated": 2,
                },
            },
        )
        self.assertEqual(response.data["attention"]["projects_awaiting_evaluation"], 1)

    def test_open_evaluation_limit_is_informational_only(self):
        self.program.max_project_rates = 3
        self.program.save(update_fields=["max_project_rates"])
        project = create_project(name="Open evaluation")
        create_program_project(self.program, project=project, submitted=True)
        expert = create_rate_expert(
            prefix="analytics-open-expert",
            program=self.program,
        )
        criteria = Criteria.objects.create(
            name="Open impact",
            type="int",
            partner_program=self.program,
        )
        ProjectScore.objects.create(
            criteria=criteria,
            user=expert,
            project=project,
            value="8",
        )

        response = self.client.get(self.url)

        self.assertEqual(response.data["evaluation_status"]["mode"], "open")
        self.assertEqual(
            response.data["evaluation_status"]["max_evaluations_per_project"],
            3,
        )
        self.assertEqual(
            response.data["evaluation_status"]["projects"],
            {
                "submitted": 1,
                "awaiting_evaluation": 0,
                "partially_evaluated": 0,
                "evaluated": 1,
            },
        )
        self.assertEqual(response.data["solution_funnel"]["evaluated"], 1)
        self.assertEqual(response.data["attention"]["projects_awaiting_evaluation"], 0)

    def test_summary_experts_uses_program_membership_without_assignments(self):
        create_rate_expert(
            prefix="analytics-program-expert-1",
            program=self.program,
        )
        create_rate_expert(
            prefix="analytics-program-expert-2",
            program=self.program,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.data["summary"]["experts"]["total"], 2)
        self.assertEqual(
            response.data["evaluation_status"]["assignments"]["total"],
            0,
        )

    def _create_distributed_evaluation(self, *, assignments: int, scores: int):
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_distributed_evaluation"])
        project = create_project(name="Distributed evaluation")
        create_program_project(self.program, project=project, submitted=True)
        criteria = Criteria.objects.create(
            name="Distributed impact",
            type="int",
            partner_program=self.program,
        )
        experts = [
            create_rate_expert(
                prefix=f"analytics-distributed-expert-{index}",
                program=self.program,
            )
            for index in range(assignments)
        ]
        for expert in experts:
            ProjectExpertAssignment.objects.create(
                partner_program=self.program,
                project=project,
                expert=expert.expert,
            )
        for expert in experts[:scores]:
            ProjectScore.objects.create(
                criteria=criteria,
                user=expert,
                project=project,
                value="8",
            )

    def test_distributed_project_without_assignments_is_awaiting_evaluation(self):
        self._create_distributed_evaluation(assignments=0, scores=0)

        response = self.client.get(self.url)

        self.assertEqual(response.data["evaluation_status"]["mode"], "distributed")
        self.assertEqual(
            response.data["evaluation_status"]["projects"],
            {
                "submitted": 1,
                "awaiting_evaluation": 1,
                "partially_evaluated": 0,
                "evaluated": 0,
            },
        )
        self.assertEqual(response.data["attention"]["projects_awaiting_evaluation"], 1)

    def test_distributed_assignments_without_scores_are_awaiting_evaluation(self):
        self._create_distributed_evaluation(assignments=2, scores=0)

        response = self.client.get(self.url)

        self.assertEqual(
            response.data["evaluation_status"]["projects"]["awaiting_evaluation"],
            1,
        )
        self.assertEqual(
            response.data["evaluation_status"]["assignments"],
            {"total": 2, "pending": 2, "evaluated": 0},
        )

    def test_distributed_project_with_one_of_two_scores_is_partial(self):
        self._create_distributed_evaluation(assignments=2, scores=1)

        response = self.client.get(self.url)

        self.assertEqual(
            response.data["evaluation_status"]["projects"]["partially_evaluated"],
            1,
        )
        self.assertEqual(response.data["solution_funnel"]["evaluated"], 0)
        self.assertEqual(response.data["attention"]["projects_awaiting_evaluation"], 1)

    def test_distributed_project_with_all_assignment_scores_is_evaluated(self):
        self._create_distributed_evaluation(assignments=2, scores=2)

        response = self.client.get(self.url)

        self.assertEqual(
            response.data["evaluation_status"]["projects"]["evaluated"],
            1,
        )
        self.assertEqual(response.data["solution_funnel"]["evaluated"], 1)
        self.assertEqual(response.data["attention"]["projects_awaiting_evaluation"], 0)

    def test_activity_groups_events_and_fills_thirty_day_range(self):
        participant = create_program_member(self.program)
        submitted_link = create_program_project(
            self.program,
            submitted=True,
        )
        event_datetime = timezone.now() - timedelta(days=2)
        PartnerProgramUserProfile.objects.filter(pk=participant.pk).update(
            datetime_created=event_datetime
        )
        type(submitted_link).objects.filter(pk=submitted_link.pk).update(
            datetime_submitted=event_datetime
        )

        response = self.client.get(self.url)

        activity = response.data["activity"]
        event_date = timezone.localdate(event_datetime).isoformat()
        event_item = next(item for item in activity if item["date"] == event_date)
        self.assertEqual(len(activity), 30)
        self.assertEqual(event_item["registrations"], 1)
        self.assertEqual(event_item["submitted_solutions"], 1)
        self.assertTrue(
            any(
                item["registrations"] == 0 and item["submitted_solutions"] == 0
                for item in activity
            )
        )

    def test_empty_program_returns_zero_metrics_and_continuous_activity(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["participants"]["total"], 0)
        self.assertEqual(response.data["summary"]["projects"]["total"], 0)
        self.assertEqual(response.data["summary"]["experts"]["total"], 0)
        self.assertEqual(response.data["summary"]["regions"], {"total": 0, "items": []})
        self.assertEqual(len(response.data["activity"]), 30)
        self.assertTrue(
            all(
                item["registrations"] == 0 and item["submitted_solutions"] == 0
                for item in response.data["activity"]
            )
        )
        self.assertNotIn("cases", response.data)

    def test_query_count_does_not_grow_with_program_size(self):
        with CaptureQueriesContext(connection) as empty_context:
            empty_response = self.client.get(self.url)
        self.assertEqual(empty_response.status_code, 200)

        for index in range(12):
            participant = create_user(prefix=f"analytics-query-participant-{index}")
            create_program_member(self.program, user=participant)
            create_program_project(
                self.program,
                project=create_project(leader=participant, region=f"Region {index}"),
                submitted=index % 2 == 0,
            )

        with CaptureQueriesContext(connection) as populated_context:
            populated_response = self.client.get(self.url)
        self.assertEqual(populated_response.status_code, 200)

        self.assertEqual(len(populated_context), len(empty_context))
        self.assertLessEqual(len(populated_context), 10)
