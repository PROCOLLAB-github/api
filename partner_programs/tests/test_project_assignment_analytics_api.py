from copy import deepcopy
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    Evaluation,
    PartnerProgram,
    PartnerProgramProject,
    Submission,
    SubmissionExpertAssignment,
    Team,
    TeamMember,
)
from partner_programs.serializers.project_assignment_analytics import (
    ProjectAssignmentAnalyticsSerializer,
    ProjectAssignmentScoresSerializer,
    ProjectDelayedExpertsSerializer,
)
from partner_programs.services.project_analytics import build_project_analytics
from partner_programs.services.project_assignment_analytics import (
    build_assignments,
    build_delayed_experts,
)
from partner_programs.tests import test_manager_program_overview_api as production_tests
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_user,
)
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_expert

NOW = datetime(2026, 9, 5, 12, tzinfo=datetime_timezone.utc)
SAFE_EXPERT_FIELDS = {
    "expert_id",
    "user_id",
    "first_name",
    "last_name",
    "full_name",
    "avatar",
}


class ProjectAssignmentAnalyticsFixture:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.manager = create_user(password=None)
        cls.program = create_partner_program(
            is_distributed_evaluation=True, max_project_rates=3
        )
        cls.program.managers.add(cls.manager)
        cls.expert = create_rate_expert(program=cls.program)
        # Program creation adds a comment criterion; use exactly five here.
        cls.program.criterias.all().delete()
        cls.criteria = [
            Criteria.objects.create(
                partner_program=cls.program,
                name=f"Criterion {index}",
                description="Description",
                type="int",
                min_value=0,
                max_value=10,
            )
            for index in range(5)
        ]

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = self.list_url(self.program.pk)
        self.overview_url = reverse(
            "partner_programs:project-analytics", kwargs={"program_id": self.program.pk}
        )
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.addCleanup(cache.clear)

    @staticmethod
    def list_url(program_id):
        return reverse(
            "partner_programs:project-analytics-assignments",
            kwargs={"program_id": program_id},
        )

    def scores_url(self, assignment_id, program_id=None):
        return reverse(
            "partner_programs:project-analytics-assignment-scores",
            kwargs={
                "program_id": program_id or self.program.pk,
                "assignment_id": assignment_id,
            },
        )

    def assignment(self, *, submitted=True, hours=25, expert=None, program=None):
        program = program or self.program
        expert = expert or self.expert
        link = create_program_project(program, submitted=submitted)
        assigned = ProjectExpertAssignment.objects.create(
            partner_program=program, project=link.project, expert=expert.expert
        )
        timestamp = NOW - timedelta(hours=hours)
        ProjectExpertAssignment.objects.filter(pk=assigned.pk).update(
            datetime_created=timestamp
        )
        PartnerProgramProject.objects.filter(pk=link.pk).update(
            datetime_submitted=timestamp if submitted else None
        )
        return assigned

    def score(self, assignment, count=5):
        for criterion in self.criteria[:count]:
            ProjectScore.objects.get_or_create(
                criteria=criterion,
                project_id=assignment.project_id,
                user_id=assignment.expert.user_id,
                defaults={"value": "0"},
            )

    def get(self, url=None, **params):
        response = self.client.get(url or self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.json()

    def delayed(self):
        return self.get(self.overview_url)["attention"]["delayed_experts"]


class ProjectAssignmentCompletionTests(ProjectAssignmentAnalyticsFixture, TestCase):
    def test_zero_one_and_all_five_scores_and_new_criterion(self):
        assignment = self.assignment()
        for count, status in ((0, "pending"), (1, "in_progress"), (5, "completed")):
            with self.subTest(count=count):
                self.score(assignment, count)
                item = self.get()[0]
                self.assertEqual(item["status"], status)
                self.assertEqual(item["criteria_total"], 5)
                self.assertEqual(item["criteria_scored"], count)
                metrics = self.get(self.overview_url)["evaluation_status"]["assignments"]
                self.assertEqual(
                    metrics,
                    {"total": 1, "pending": int(count < 5), "evaluated": int(count == 5)},
                )
        Criteria.objects.create(partner_program=self.program, name="New", type="str")
        self.assertEqual(self.get()[0]["status"], "in_progress")
        self.assertEqual(
            self.get(self.overview_url)["evaluation_status"]["assignments"]["pending"], 1
        )

    def test_zero_criteria_is_pending(self):
        self.program.criterias.all().delete()
        self.assignment()
        item = self.get()[0]
        self.assertEqual((item["criteria_total"], item["criteria_scored"]), (0, 0))
        self.assertEqual(item["status"], "pending")

    def test_unsubmitted_even_with_all_scores_is_not_ready(self):
        assignment = self.assignment(submitted=False, hours=100)
        self.score(assignment)
        item = self.get()[0]
        self.assertEqual(item["status"], "not_ready")
        self.assertFalse(item["project_submitted"])
        for key in ("project_submitted_at", "waiting_since", "waiting_seconds"):
            self.assertIsNone(item[key])

    def test_foreign_expert_project_and_program_scores_do_not_count(self):
        assignment = self.assignment()
        other_project = self.assignment()
        self.score(other_project)
        other_expert = create_rate_expert(program=self.program)
        for criterion in self.criteria:
            ProjectScore.objects.create(
                project=assignment.project,
                user=other_expert,
                criteria=criterion,
                value="8",
            )
        foreign_criterion = Criteria.objects.create(
            partner_program=create_partner_program(), name="Other program", type="str"
        )
        ProjectScore.objects.create(
            project=assignment.project,
            user=self.expert,
            criteria=foreign_criterion,
            value="foreign",
        )
        self.assertEqual(self.get()[0]["criteria_scored"], 0)
        self.score(assignment, 1)
        item = self.get()[0]
        self.assertEqual(item["criteria_scored"], 1)
        self.assertEqual(item["status"], "in_progress")
        scores = self.get(self.scores_url(assignment.pk))["scores"]
        self.assertEqual(
            [item["value"] for item in scores], ["0", None, None, None, None]
        )

    def test_scopes_include_all_noncompleted_statuses_and_preserve_pk_order(self):
        self.assignment(submitted=False)
        self.assignment()
        self.score(self.assignment(), 1)
        completed = self.assignment()
        self.score(completed)
        items = self.get()
        self.assertEqual(self.get(scope="all"), items)
        self.assertEqual(
            [item["assignment_id"] for item in items],
            sorted(item["assignment_id"] for item in items),
        )
        self.assertEqual(
            [item["status"] for item in self.get(scope="pending")],
            ["not_ready", "pending", "in_progress"],
        )
        self.assertEqual(
            [item["assignment_id"] for item in self.get(scope="completed")],
            [completed.pk],
        )
        self.assertEqual(
            self.get(self.overview_url)["evaluation_status"]["assignments"],
            {"total": 4, "pending": 3, "evaluated": 1},
        )

    def test_invalid_and_empty_scopes_are_400(self):
        for scope in ("", "unknown", "COMPLETED", "evaluated", " "):
            with self.subTest(scope=scope):
                self.assertEqual(
                    self.client.get(self.url, {"scope": scope}).status_code, 400
                )

    def test_distributed_project_transitions_reuse_completed_not_score_counts(self):
        first = self.assignment()
        second = ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=first.project,
            expert=create_rate_expert(program=self.program).expert,
        )
        self.score(first, 1)
        self.score(second, 1)
        for complete, expected in (
            (None, "awaiting_evaluation"),
            (first, "partially_evaluated"),
            (second, "evaluated"),
        ):
            if complete:
                self.score(complete)
            payload = self.get(self.overview_url)
            self.assertEqual(payload["evaluation_status"]["projects"][expected], 1)
            self.assertEqual(
                payload["solution_funnel"]["evaluated"], int(expected == "evaluated")
            )
        # Two actual assignments suffice despite max_project_rates=3.
        create_program_project(self.program, submitted=True)
        self.assertEqual(
            self.get(self.overview_url)["evaluation_status"]["projects"][
                "awaiting_evaluation"
            ],
            1,
        )

    def test_open_mode_uses_any_score_without_synthetic_assignments(self):
        self.program.is_distributed_evaluation = False
        self.program.save(update_fields=["is_distributed_evaluation"])
        link = create_program_project(self.program, submitted=True)
        ProjectScore.objects.create(
            project=link.project, user=self.expert, criteria=self.criteria[0], value="1"
        )
        self.assertEqual(self.get(), [])
        self.assertEqual(self.get(self.overview_url)["solution_funnel"]["evaluated"], 1)
        real = self.assignment(hours=100)
        self.assertEqual(self.get()[0]["assignment_id"], real.pk)
        self.assertEqual(self.delayed(), {"total": 0, "items": []})


class ProjectAssignmentScoresTests(ProjectAssignmentAnalyticsFixture, TestCase):
    def test_all_criteria_in_pk_order_with_metadata_and_missing_rows(self):
        assignment = self.assignment()
        self.score(assignment, 1)
        payload = self.get(self.scores_url(assignment.pk))
        self.assertEqual(
            {key: value for key, value in payload.items() if key != "scores"},
            self.get()[0],
        )
        scores = payload["scores"]
        self.assertEqual(
            [item["criterion_id"] for item in scores], [c.pk for c in self.criteria]
        )
        for index, item in enumerate(scores):
            self.assertEqual(
                item,
                {
                    "criterion_id": self.criteria[index].pk,
                    "name": self.criteria[index].name,
                    "description": "Description",
                    "type": "int",
                    "min_value": 0,
                    "max_value": 10,
                    "value": "0" if index == 0 else None,
                    "is_scored": index == 0,
                },
            )

    def test_string_blank_null_and_numeric_looking_values_preserved_exactly(self):
        assignment = self.assignment()
        values = ["  text\t ", "", None, "000.50", "false"]
        for criterion, value in zip(self.criteria, values):
            criterion.type = "str"
            criterion.save(update_fields=["type"])
            ProjectScore.objects.create(
                criteria=criterion,
                project=assignment.project,
                user=self.expert,
                value=value,
            )
        payload = self.get(self.scores_url(assignment.pk))
        self.assertEqual([item["value"] for item in payload["scores"]], values)
        self.assertTrue(all(item["is_scored"] for item in payload["scores"]))
        self.assertEqual(payload["status"], "completed")
        with self.assertNumQueries(0):
            serializer = ProjectAssignmentScoresSerializer(data=payload)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(serializer.data, payload)

    def test_foreign_assignment_is_404_even_for_manager_of_both_programs(self):
        other = create_partner_program()
        other.managers.add(self.manager)
        self.expert.expert.programs.add(other)
        assignment = self.assignment(program=other)
        self.assertEqual(self.client.get(self.scores_url(assignment.pk)).status_code, 404)
        self.assertEqual(self.get(), [])

    def test_same_project_uses_own_program_link_timestamps_criteria_and_assignment(self):
        assignment_a = self.assignment(hours=100)
        self.score(assignment_a)
        other = create_partner_program(is_distributed_evaluation=True)
        other.managers.add(self.manager)
        self.expert.expert.programs.add(other)
        link_b = create_program_project(
            other, project=assignment_a.project, submitted=False
        )
        assignment_b = ProjectExpertAssignment.objects.create(
            partner_program=other, project=assignment_a.project, expert=self.expert.expert
        )
        ProjectExpertAssignment.objects.filter(pk=assignment_b.pk).update(
            datetime_created=NOW - timedelta(hours=60)
        )
        url_b = self.list_url(other.pk)
        row_b = self.get(url_b)[0]
        self.assertEqual(row_b["assignment_id"], assignment_b.pk)
        self.assertEqual(row_b["status"], "not_ready")
        self.assertEqual(row_b["criteria_scored"], 0)
        self.assertIsNone(row_b["project_submitted_at"])
        timestamp_b = NOW - timedelta(hours=25)
        PartnerProgramProject.objects.filter(pk=link_b.pk).update(
            submitted=True, datetime_submitted=timestamp_b
        )
        row_b = self.get(url_b)[0]
        self.assertEqual(row_b["status"], "pending")
        self.assertEqual(row_b["waiting_seconds"], 25 * 3600)
        self.assertEqual(
            datetime.fromisoformat(row_b["project_submitted_at"]), timestamp_b
        )
        scores_b = self.get(self.scores_url(assignment_b.pk, other.pk))["scores"]
        self.assertEqual(
            [item["criterion_id"] for item in scores_b],
            list(other.criterias.values_list("pk", flat=True)),
        )
        self.assertTrue(all(not item["is_scored"] for item in scores_b))
        row_a = self.get()[0]
        self.assertEqual(row_a["assignment_id"], assignment_a.pk)
        self.assertEqual(row_a["status"], "completed")
        self.assertEqual(
            datetime.fromisoformat(row_a["project_submitted_at"]),
            NOW - timedelta(hours=100),
        )
        self.assertEqual(self.delayed(), {"total": 0, "items": []})


class ProjectAssignmentWaitingTests(ProjectAssignmentAnalyticsFixture, TestCase):
    def test_later_of_submission_and_assignment_is_waiting_start(self):
        assignment = self.assignment()
        for assigned_hours, submitted_hours in ((4, 2), (1, 4)):
            with self.subTest(assigned=assigned_hours, submitted=submitted_hours):
                assigned_at = NOW - timedelta(hours=assigned_hours)
                submitted_at = NOW - timedelta(hours=submitted_hours)
                ProjectExpertAssignment.objects.filter(pk=assignment.pk).update(
                    datetime_created=assigned_at
                )
                PartnerProgramProject.objects.filter(
                    partner_program=self.program, project=assignment.project
                ).update(datetime_submitted=submitted_at)
                item = build_assignments(self.program.pk)[0]
                self.assertEqual(item["waiting_since"], max(assigned_at, submitted_at))
                self.assertEqual(
                    item["waiting_seconds"], min(assigned_hours, submitted_hours) * 3600
                )

    def test_missing_timestamp_completed_and_not_ready_do_not_trigger_waiting_or_sla(
        self,
    ):
        self.score(self.assignment(hours=100))
        self.assignment(hours=100, submitted=False)
        missing = self.assignment(hours=100)
        PartnerProgramProject.objects.filter(
            partner_program=self.program, project=missing.project
        ).update(datetime_submitted=None)
        for item in self.get():
            self.assertIsNone(item["waiting_since"])
            self.assertIsNone(item["waiting_seconds"])
        self.assertEqual(self.delayed(), {"total": 0, "items": []})

    def test_future_waiting_is_clamped_to_zero(self):
        self.assignment(hours=-5)
        item = self.get()[0]
        self.assertEqual(item["waiting_seconds"], 0)
        self.assertEqual(
            datetime.fromisoformat(item["waiting_since"]), NOW + timedelta(hours=5)
        )
        self.assertEqual(self.delayed(), {"total": 0, "items": []})

    def test_exact_sla_thresholds(self):
        cases = (
            (1, 24, None),
            (2, 24, "warning"),
            (1, 48, "critical"),
            (2, 24 - 1 / 3600, None),
            (1, 48 - 1 / 3600, None),
        )
        for count, hours, severity in cases:
            expert = create_rate_expert(program=self.program)
            for _ in range(count):
                self.assignment(hours=hours, expert=expert)
            items = [
                item
                for item in self.delayed()["items"]
                if item["expert_id"] == expert.expert.pk
            ]
            with self.subTest(count=count, hours=hours):
                self.assertEqual(len(items), int(severity is not None))
                if items:
                    item = items[0]
                    self.assertEqual(item["severity"], severity)
                    self.assertEqual(item["assignments_total"], count)
                    self.assertEqual(item["pending"], count)
                    self.assertEqual(item["completed"], 0)
                    self.assertEqual(item["overdue_24h"], count)
                    self.assertEqual(item["overdue_48h"], count if hours >= 48 else 0)
                    self.assertEqual(item["oldest_waiting_seconds"], int(hours * 3600))

    def test_totals_include_completed_not_ready_and_missing_timestamp_but_sla_does_not(
        self,
    ):
        self.score(self.assignment(hours=100))
        self.assignment(hours=100, submitted=False)
        missing = self.assignment(hours=100)
        PartnerProgramProject.objects.filter(
            partner_program=self.program, project=missing.project
        ).update(datetime_submitted=None)
        self.score(self.assignment(hours=49), 1)
        item = self.delayed()["items"][0]
        self.assertEqual(item["assignments_total"], 4)
        self.assertEqual(item["completed"], 1)
        self.assertEqual(item["pending"], 3)
        self.assertEqual(item["overdue_24h"], 1)
        self.assertEqual(item["overdue_48h"], 1)
        self.assertEqual(item["oldest_waiting_seconds"], 49 * 3600)

    def test_deterministic_severity_wait_and_expert_id_order(self):
        warning = create_rate_expert(program=self.program)
        for _ in range(2):
            self.assignment(expert=warning, hours=25)
        tie = create_rate_expert(program=self.program)
        self.assignment(expert=tie, hours=49)
        self.assignment(hours=49)
        oldest = create_rate_expert(program=self.program)
        self.assignment(expert=oldest, hours=60)
        self.assertEqual(
            [item["expert_id"] for item in self.delayed()["items"]],
            [oldest.expert.pk, self.expert.expert.pk, tie.expert.pk, warning.expert.pk],
        )


class ProjectAssignmentAccessTests(ProjectAssignmentAnalyticsFixture, TestCase):
    def test_manager_staff_superuser_allowed_and_other_roles_denied(self):
        assignment = self.assignment()
        participant = create_user(password=None)
        create_program_member(self.program, user=participant)
        other_manager = create_user(password=None)
        create_partner_program().managers.add(other_manager)
        for user, status in (
            (self.manager, 200),
            (create_user(password=None, is_staff=True), 200),
            (create_user(password=None, is_superuser=True, is_staff=False), 200),
            (participant, 403),
            (self.expert, 403),
            (other_manager, 403),
            (None, 401),
        ):
            self.client.force_authenticate(user)
            for url in (self.url, self.scores_url(assignment.pk)):
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.get(url).status_code, status)

    def test_unknown_program_or_assignment_gets_404(self):
        assignment = self.assignment()
        for url in (
            self.list_url(999999),
            self.scores_url(assignment.pk, 999999),
            self.scores_url(999999),
        ):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_mutating_methods_are_405(self):
        assignment = self.assignment()
        for url in (self.url, self.scores_url(assignment.pk)):
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(url=url, method=method):
                    self.assertEqual(
                        getattr(self.client, method)(url, {}, format="json").status_code,
                        405,
                    )


class ProjectAssignmentIsolationTests(ProjectAssignmentAnalyticsFixture, TestCase):
    def test_production_entities_do_not_change_legacy_assignments_scores_or_overview(
        self,
    ):
        legacy = self.assignment(hours=49)
        self.score(legacy, 1)
        before = [
            self.get(),
            self.get(self.scores_url(legacy.pk)),
            self.get(self.overview_url),
        ]
        user = create_user(password=None)
        application = Application.objects.create(
            program=self.program,
            user=user,
            created_by=user,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        )
        team = Team.objects.create(application=application, captain=user)
        TeamMember.objects.create(
            team=team,
            user=user,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )
        submission = Submission.objects.create(
            application=application,
            program=self.program,
            submitted_by=user,
            title="Production only",
            status=Submission.STATUS_SUBMITTED,
        )
        SubmissionExpertAssignment.objects.create(
            submission=submission, expert=self.expert.expert, assigned_by=self.manager
        )
        Evaluation.objects.create(submission=submission, expert=self.expert.expert)
        self.assertEqual(
            [
                self.get(),
                self.get(self.scores_url(legacy.pk)),
                self.get(self.overview_url),
            ],
            before,
        )
        with CaptureQueriesContext(connection) as queries:
            self.get()
            self.get(self.scores_url(legacy.pk))
            self.get(self.overview_url)
        for model in (
            Application,
            Team,
            TeamMember,
            Submission,
            SubmissionExpertAssignment,
            Evaluation,
        ):
            for query in queries:
                self.assertNotIn(f'"{model._meta.db_table}"', query["sql"])
        self.assertTrue(
            all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)
        )

    def test_legacy_data_does_not_change_production_manager_assignment_or_evaluation_apis(
        self,
    ):
        fixture = production_tests.ManagerProgramOverviewAPITests()
        fixture.program = self.program
        fixture.seed_complete_overview(self.program, self.manager, "assignment-isolation")
        evaluation = Evaluation.objects.filter(submission__program=self.program).first()
        urls = [
            reverse("partner_programs:" + name, kwargs={"program_id": self.program.pk})
            for name in (
                "manager-overview",
                "submission-assignment-list-create",
                "evaluation-list",
            )
        ]
        urls.append(
            reverse(
                "partner_programs:evaluation-detail",
                kwargs={"program_id": self.program.pk, "evaluation_id": evaluation.pk},
            )
        )
        before = [self.get(url) for url in urls]
        legacy = self.assignment(hours=49)
        self.score(legacy)
        self.assertEqual([self.get(url) for url in urls], before)


class ProjectAssignmentContractTests(ProjectAssignmentAnalyticsFixture, TestCase):
    def test_all_b5_b6a_fields_are_preserved_apart_from_b6b_additions(self):
        assignments = [
            self.assignment(submitted=False),
            self.assignment(),
            self.assignment(),
            self.assignment(),
        ]
        self.score(assignments[2], 1)
        self.score(assignments[3])
        for assignment, region in zip(assignments, (" North ", "North", "South", None)):
            project = assignment.project
            project.region = region
            project.save(update_fields=["region"])
            user = project.leader
            user.city = " City "
            user.save(update_fields=["city"])
            create_program_member(self.program, user=user)
        create_program_member(self.program, user=create_user(password=None, city=""))
        today = timezone.localdate(NOW)
        submitted_day = timezone.localdate(NOW - timedelta(hours=25))
        for distributed in (False, True):
            self.program.is_distributed_evaluation = distributed
            # Switch only the mode without the save signal adding a sixth criterion.
            PartnerProgram.objects.filter(pk=self.program.pk).update(
                is_distributed_evaluation=distributed
            )
            payload = self.get(self.overview_url)
            self.assertIn("delayed_experts", payload["attention"])
            del payload["attention"]["delayed_experts"]
            del payload["attention"]["projects_not_submitted"]
            del payload["cases"]
            evaluated = 1 if distributed else 2
            self.assertEqual(
                payload,
                {
                    "summary": {
                        "participants": {"total": 5},
                        "projects": {"total": 4},
                        "experts": {"total": 1},
                        "regions": {
                            "total": 2,
                            "items": [
                                {"name": "North", "count": 2},
                                {"name": "South", "count": 1},
                            ],
                        },
                        "participant_regions": {
                            "total": 1,
                            "items": [{"name": "City", "count": 4}],
                        },
                    },
                    "participant_funnel": {
                        "registrations": 5,
                        "unique_participants": 5,
                        "with_team": 4,
                        "project_creators": 4,
                        "submitted_project_creators": 3,
                    },
                    "solution_funnel": {
                        "created": 4,
                        "not_submitted": 1,
                        "submitted": 3,
                        "evaluated": evaluated,
                    },
                    "evaluation_status": {
                        "mode": "distributed" if distributed else "open",
                        "max_evaluations_per_project": 3,
                        "assignments": {"total": 4, "pending": 3, "evaluated": 1},
                        "projects": {
                            "submitted": 3,
                            "awaiting_evaluation": 3 - evaluated,
                            "partially_evaluated": 0,
                            "evaluated": evaluated,
                        },
                    },
                    "attention": {
                        "participants_without_team": 1,
                        "projects_awaiting_evaluation": 3 - evaluated,
                    },
                    "activity": [
                        {
                            "date": day.isoformat(),
                            "registrations": 5 if day == today else 0,
                            "submitted_solutions": 3 if day == submitted_day else 0,
                        }
                        for day in (
                            today - timedelta(days=29 - index) for index in range(30)
                        )
                    ],
                },
            )

    def test_explicit_safe_contract_and_sql_free_serializers(self):
        assignment = self.assignment(hours=49)
        payload = self.get(self.scores_url(assignment.pk))
        self.assertEqual(
            set(payload) - {"scores"},
            {
                "assignment_id",
                "expert",
                "project",
                "status",
                "criteria_total",
                "criteria_scored",
                "assigned_at",
                "project_submitted",
                "project_submitted_at",
                "waiting_since",
                "waiting_seconds",
            },
        )
        self.assertEqual(set(payload["expert"]), SAFE_EXPERT_FIELDS)
        self.assertEqual(set(payload["project"]), {"id", "name"})
        delayed = self.delayed()
        self.assertEqual(
            set(delayed["items"][0]),
            SAFE_EXPERT_FIELDS
            | {
                "assignments_total",
                "completed",
                "pending",
                "overdue_24h",
                "overdue_48h",
                "oldest_waiting_since",
                "oldest_waiting_seconds",
                "severity",
            },
        )
        for serializer_class, data in (
            (ProjectAssignmentScoresSerializer, payload),
            (ProjectDelayedExpertsSerializer, delayed),
        ):
            with self.assertNumQueries(0):
                serializer = serializer_class(data=data)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.data, data)
        assignments = build_assignments(self.program.pk)
        with self.assertNumQueries(0):
            self.assertEqual(build_delayed_experts(assignments)["total"], 1)

    def test_strict_status_severity_and_nonnegative_counts(self):
        self.assignment(hours=49)
        item = self.get()[0]
        for field, value in (
            ("status", "evaluated"),
            ("criteria_total", -1),
            ("criteria_scored", -1),
            ("waiting_seconds", -1),
        ):
            with self.subTest(field=field), self.assertNumQueries(0):
                self.assertFalse(
                    ProjectAssignmentAnalyticsSerializer(
                        data={**item, field: value}
                    ).is_valid()
                )
        delayed = self.delayed()
        for field in (
            "assignments_total",
            "completed",
            "pending",
            "overdue_24h",
            "overdue_48h",
            "oldest_waiting_seconds",
            "severity",
        ):
            invalid = deepcopy(delayed)
            invalid["items"][0][field] = "unknown" if field == "severity" else -1
            with self.subTest(field=field), self.assertNumQueries(0):
                self.assertFalse(ProjectDelayedExpertsSerializer(data=invalid).is_valid())
        self.assertFalse(
            ProjectDelayedExpertsSerializer(data={**delayed, "total": -1}).is_valid()
        )

    def test_fixed_query_budgets_one_vs_thirty_one_assignments(self):
        first = self.assignment(hours=49)
        self.score(first, 1)
        for size in (1, 31):
            if size == 31:
                for _ in range(30):
                    self.score(
                        self.assignment(expert=create_rate_expert(program=self.program)),
                        1,
                    )
            for url, budget in (
                (self.url, 3),
                (self.overview_url, 14),
                (self.scores_url(first.pk), 5),
            ):
                with self.subTest(size=size, url=url), CaptureQueriesContext(
                    connection
                ) as queries:
                    self.get(url)
                self.assertEqual(len(queries), budget)
            with self.assertNumQueries(12):
                build_project_analytics(self.program)

    def test_scores_query_budget_one_vs_twenty_criteria(self):
        assignment = self.assignment()
        self.program.criterias.all().delete()
        for size in (1, 20):
            for index in range(1 if size == 1 else 19):
                Criteria.objects.create(
                    partner_program=self.program,
                    name=f"Criterion {size}-{index}",
                    type="str",
                )
            with CaptureQueriesContext(connection) as queries:
                payload = self.get(self.scores_url(assignment.pk))
            self.assertEqual(len(queries), 5)
            self.assertEqual(len(payload["scores"]), size)
