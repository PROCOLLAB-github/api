import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.manager_overview_views import ManagerProgramOverviewView
from partner_programs.models import (
    Application,
    Evaluation,
    PartnerProgramProject,
    PartnerProgramUserProfile,
    Submission,
    SubmissionExpertAssignment,
    Team,
    TeamMember,
)
from partner_programs.project_analytics_views import ProjectAnalyticsAPIView
from partner_programs.serializers.project_analytics import ProjectAnalyticsSerializer
from partner_programs.services.project_analytics import build_project_analytics
from partner_programs.tests import test_manager_program_overview_api as production_tests
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_criteria, create_rate_expert
from projects.models import Collaborator


class ProjectAnalyticsFixture:
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = APIClient()
        self.manager = create_user(password=None)
        self.program = create_partner_program(max_project_rates=2)
        self.program.managers.add(self.manager)
        self.client.force_authenticate(self.manager)
        self.url = self.analytics_url(self.program)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    @staticmethod
    def analytics_url(program):
        return reverse(
            "partner_programs:project-analytics", kwargs={"program_id": program.pk}
        )

    def overview(self, program=None):
        response = self.client.get(self.analytics_url(program or self.program))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def assignment(self, project, expert, program=None):
        return ProjectExpertAssignment.objects.create(
            partner_program=program or self.program, project=project, expert=expert.expert
        )

    @staticmethod
    def score(project, expert, criterion):
        return ProjectScore.objects.create(
            project=project, user=expert, criteria=criterion, value="8"
        )


class ProjectAnalyticsAccessTests(ProjectAnalyticsFixture, TestCase):
    def test_manager_staff_and_superuser_can_read(self):
        for user in (
            self.manager,
            create_user(password=None, is_staff=True),
            create_user(password=None, is_superuser=True, is_staff=False),
        ):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_participant_expert_and_other_program_manager_are_forbidden(self):
        participant = create_user(password=None)
        create_program_member(self.program, user=participant)
        expert = create_rate_expert(program=self.program)
        other_manager = create_user(password=None)
        create_partner_program().managers.add(other_manager)
        for user in (participant, expert, other_manager):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_gets_401(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_unknown_program_gets_404(self):
        url = reverse("partner_programs:project-analytics", kwargs={"program_id": 999999})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_mutating_methods_get_405(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url, {}, format="json")
                self.assertEqual(response.status_code, 405)

    def test_namespaces_resolve_to_different_views(self):
        manager_url = reverse(
            "partner_programs:manager-overview", kwargs={"program_id": self.program.pk}
        )
        self.assertEqual(self.url, f"/programs/{self.program.pk}/project-analytics/")
        self.assertIs(resolve(self.url).func.view_class, ProjectAnalyticsAPIView)
        self.assertIs(resolve(manager_url).func.view_class, ManagerProgramOverviewView)


class ProjectAnalyticsMetricsTests(ProjectAnalyticsFixture, TestCase):
    def test_empty_contract_has_only_b5_fields_and_thirty_zero_days(self):
        payload = self.overview()
        self.assertEqual(
            set(payload),
            {
                "summary",
                "participant_funnel",
                "solution_funnel",
                "evaluation_status",
                "attention",
                "activity",
            },
        )
        self.assertEqual(
            payload["summary"],
            {
                "participants": {"total": 0},
                "projects": {"total": 0},
                "experts": {"total": 0},
                "regions": {"total": 0, "items": []},
                "participant_regions": {"total": 0, "items": []},
            },
        )
        self.assertEqual(
            payload["participant_funnel"],
            {
                "registrations": 0,
                "unique_participants": 0,
                "with_team": 0,
                "project_creators": 0,
                "submitted_project_creators": 0,
            },
        )
        self.assertEqual(
            payload["solution_funnel"],
            {"created": 0, "not_submitted": 0, "submitted": 0, "evaluated": 0},
        )
        self.assertEqual(
            payload["attention"],
            {"participants_without_team": 0, "projects_awaiting_evaluation": 0},
        )
        today = timezone.localdate()
        self.assertEqual(
            payload["activity"],
            [
                {
                    "date": (today - timedelta(days=29 - offset)).isoformat(),
                    "registrations": 0,
                    "submitted_solutions": 0,
                }
                for offset in range(30)
            ],
        )

    def test_participants_use_distinct_registered_leaders_and_collaborators(self):
        leader, collaborator, no_team = [create_user(password=None) for _ in range(3)]
        for user in (leader, collaborator, no_team):
            create_program_member(self.program, user=user)
        for _ in range(2):
            PartnerProgramUserProfile.objects.create(
                partner_program=self.program, user=None, partner_program_data={}
            )
        for submitted in (False, True):
            project = create_project(leader=leader)
            create_program_project(self.program, project=project, submitted=submitted)
            for user in (leader, collaborator):
                Collaborator.objects.get_or_create(project=project, user=user)
        # An unregistered leader counts as a project, not as a participant/creator.
        create_program_project(self.program, submitted=True)
        payload = self.overview()
        self.assertEqual(payload["summary"]["participants"], {"total": 3})
        self.assertEqual(payload["summary"]["projects"], {"total": 3})
        self.assertEqual(
            payload["participant_funnel"],
            {
                "registrations": 5,
                "unique_participants": 3,
                "with_team": 2,
                "project_creators": 1,
                "submitted_project_creators": 1,
            },
        )
        self.assertEqual(payload["attention"]["participants_without_team"], 1)

    def test_profile_project_and_team_in_another_program_do_not_count(self):
        user = create_user(password=None)
        foreign = create_partner_program()
        create_program_member(foreign, user=user)
        for leader in (user, create_user(password=None)):
            project = create_project(leader=leader)
            create_program_project(foreign, project=project, submitted=True)
        Collaborator.objects.create(user=user, project=project)
        create_program_member(self.program, user=user, project=project)
        payload = self.overview()
        self.assertEqual(payload["participant_funnel"]["with_team"], 0)
        self.assertEqual(payload["participant_funnel"]["project_creators"], 0)
        self.assertEqual(payload["participant_funnel"]["submitted_project_creators"], 0)

    def test_regions_trim_all_whitespace_without_spelling_or_case_normalization(self):
        values = (
            None,
            "",
            " \t\n\u00a0 ",
            " Moscow\t",
            "Moscow",
            "moscow",
            "Moscw",
            "Zed",
            "Alpha",
        )
        for value in values:
            user = create_user(password=None, city=value)
            create_program_member(self.program, user=user)
            create_program_project(
                self.program, project=create_project(leader=user, region=value)
            )
        foreign = create_partner_program()
        create_program_member(foreign, user=create_user(password=None, city="Foreign"))
        create_program_project(foreign, project=create_project(region="Foreign"))
        expected = {
            "total": 5,
            "items": [
                {"name": "Moscow", "count": 2},
                {"name": "Alpha", "count": 1},
                {"name": "Moscw", "count": 1},
                {"name": "Zed", "count": 1},
                {"name": "moscow", "count": 1},
            ],
        }
        payload = self.overview()
        self.assertEqual(payload["summary"]["regions"], expected)
        self.assertEqual(payload["summary"]["participant_regions"], expected)
        self.assertEqual(payload["summary"]["participants"]["total"], len(values))

    def test_experts_are_authoritative_program_members_not_only_assignees(self):
        for _ in range(2):
            create_rate_expert(program=self.program)
        create_rate_expert(program=create_partner_program())
        payload = self.overview()
        self.assertEqual(payload["summary"]["experts"]["total"], 2)
        self.assertEqual(payload["evaluation_status"]["assignments"]["total"], 0)

    def test_open_mode_first_score_is_enough_and_max_limit_is_not_a_target(self):
        expert = create_rate_expert(program=self.program)
        criterion = create_rate_criteria(self.program)
        create_rate_criteria(self.program)
        for submitted in (True, False):
            link = create_program_project(self.program, submitted=submitted)
            self.score(link.project, expert, criterion)
        create_program_project(self.program, submitted=True)
        payload = self.overview()
        self.assertEqual(
            payload["solution_funnel"],
            {
                "created": 3,
                "not_submitted": 1,
                "submitted": 2,
                "evaluated": 1,
            },
        )
        self.assertEqual(
            payload["evaluation_status"]["projects"],
            {
                "submitted": 2,
                "awaiting_evaluation": 1,
                "partially_evaluated": 0,
                "evaluated": 1,
            },
        )
        self.assertEqual(payload["evaluation_status"]["max_evaluations_per_project"], 2)
        self.assertEqual(payload["attention"]["projects_awaiting_evaluation"], 1)

    def test_nullable_max_limit_is_preserved(self):
        self.program.max_project_rates = None
        self.program.save(update_fields=["max_project_rates"])
        self.assertIsNone(
            self.overview()["evaluation_status"]["max_evaluations_per_project"]
        )

    def test_multi_program_link_submission_regions_scores_and_teams_are_scoped(self):
        program_b = create_partner_program()
        program_b.managers.add(self.manager)
        leader = create_user(password=None)
        collaborator = create_user(password=None)
        for program in (self.program, program_b):
            for user in (leader, collaborator):
                create_program_member(program, user=user)
        shared = create_project(leader=leader, region="Shared")
        create_program_project(self.program, project=shared, submitted=True)
        link_b = create_program_project(program_b, project=shared)
        only_a = create_project(region="Only A")
        create_program_project(self.program, project=only_a)
        Collaborator.objects.create(user=collaborator, project=only_a)
        expert = create_rate_expert(program=self.program)
        self.assignment(shared, expert)
        self.score(shared, expert, create_rate_criteria(self.program))
        overview_a, overview_b = self.overview(), self.overview(program_b)
        self.assertEqual(overview_a["summary"]["projects"]["total"], 2)
        self.assertEqual(overview_b["summary"]["projects"]["total"], 1)
        self.assertEqual(overview_a["solution_funnel"]["submitted"], 1)
        self.assertEqual(overview_b["solution_funnel"]["submitted"], 0)
        self.assertEqual(
            overview_b["summary"]["regions"],
            {"total": 1, "items": [{"name": "Shared", "count": 1}]},
        )
        self.assertEqual(overview_a["participant_funnel"]["with_team"], 2)
        self.assertEqual(overview_b["participant_funnel"]["with_team"], 1)
        link_b.submitted = True
        link_b.save(update_fields=["submitted"])
        for distributed in (False, True):
            program_b.is_distributed_evaluation = distributed
            program_b.save(update_fields=["is_distributed_evaluation"])
            overview_b = self.overview(program_b)
            self.assertEqual(
                overview_b["evaluation_status"]["projects"]["awaiting_evaluation"], 1
            )
            self.assertEqual(overview_b["evaluation_status"]["projects"]["evaluated"], 0)
            self.assertEqual(overview_b["evaluation_status"]["assignments"]["total"], 0)

    def test_activity_uses_local_dates_inclusive_window_and_only_submitted_links(self):
        today = date(2026, 6, 15)
        events = [
            datetime(2026, 6, 14, 21, 15, tzinfo=dt_timezone.utc),
            datetime(2026, 5, 16, 21, 15, tzinfo=dt_timezone.utc),
            datetime(2026, 5, 16, 20, 59, tzinfo=dt_timezone.utc),
            datetime(2026, 6, 15, 21, 0, tzinfo=dt_timezone.utc),
        ]
        for event in events:
            profile = create_program_member(self.program)
            link = create_program_project(self.program, submitted=True)
            PartnerProgramUserProfile.objects.filter(pk=profile.pk).update(
                datetime_created=event
            )
            PartnerProgramProject.objects.filter(pk=link.pk).update(
                datetime_submitted=event
            )
        draft = create_program_project(self.program)
        PartnerProgramProject.objects.filter(pk=draft.pk).update(
            datetime_submitted=events[0]
        )
        missing_time = create_program_project(self.program, submitted=True)
        PartnerProgramProject.objects.filter(pk=missing_time.pk).update(
            datetime_submitted=None
        )
        other_program = create_partner_program()
        other_profile = create_program_member(other_program)
        other_link = create_program_project(other_program, submitted=True)
        PartnerProgramUserProfile.objects.filter(pk=other_profile.pk).update(
            datetime_created=events[0]
        )
        PartnerProgramProject.objects.filter(pk=other_link.pk).update(
            datetime_submitted=events[0]
        )
        with timezone.override("Europe/Moscow"), patch(
            "partner_programs.services.project_analytics.timezone.localdate",
            return_value=today,
        ):
            activity = self.overview()["activity"]
        self.assertEqual(len(activity), 30)
        self.assertEqual(
            activity[0],
            {"date": "2026-05-17", "registrations": 1, "submitted_solutions": 1},
        )
        self.assertEqual(
            activity[-1],
            {"date": "2026-06-15", "registrations": 1, "submitted_solutions": 1},
        )
        self.assertEqual(sum(item["registrations"] for item in activity), 2)
        self.assertEqual(sum(item["submitted_solutions"] for item in activity), 2)


class ProjectAnalyticsCompletionTests(ProjectAnalyticsFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_distributed_evaluation"])
        self.link = create_program_project(self.program, submitted=True)
        self.expert = create_rate_expert(program=self.program)
        create_rate_criteria(self.program)
        self.criteria = list(self.program.criterias.order_by("pk"))
        self.assertEqual(
            len(self.criteria), 2
        )  # Includes the production comment criterion.

    def test_without_assignments_even_scored_project_is_awaiting(self):
        for criterion in self.criteria:
            self.score(self.link.project, self.expert, criterion)
        self.assertEqual(
            self.overview()["evaluation_status"]["projects"]["awaiting_evaluation"], 1
        )

    def test_unassigned_expert_scores_do_not_complete_someone_elses_assignment(self):
        self.assignment(self.link.project, self.expert)
        unassigned = create_rate_expert(program=self.program)
        for criterion in self.criteria:
            self.score(self.link.project, unassigned, criterion)
        payload = self.overview()
        self.assertEqual(
            payload["evaluation_status"]["assignments"],
            {"total": 1, "pending": 1, "evaluated": 0},
        )
        self.assertEqual(payload["solution_funnel"]["evaluated"], 0)

    def test_each_assignment_needs_all_current_criteria_and_current_expert_scores(self):
        self.assignment(self.link.project, self.expert)
        other_expert = create_rate_expert(program=self.program)
        self.assignment(self.link.project, other_expert)
        foreign_program = create_partner_program()
        self.score(self.link.project, self.expert, create_rate_criteria(foreign_program))
        self.score(self.link.project, self.expert, self.criteria[0])
        first = self.overview()
        self.assertEqual(
            first["evaluation_status"]["assignments"],
            {"total": 2, "pending": 2, "evaluated": 0},
        )
        self.assertEqual(first["evaluation_status"]["projects"]["awaiting_evaluation"], 1)
        self.score(self.link.project, self.expert, self.criteria[1])
        partial = self.overview()
        self.assertEqual(
            partial["evaluation_status"]["projects"]["partially_evaluated"], 1
        )
        self.assertEqual(partial["attention"]["projects_awaiting_evaluation"], 1)
        for criterion in self.criteria:
            self.score(self.link.project, other_expert, criterion)
        complete = self.overview()
        self.assertEqual(
            complete["evaluation_status"]["assignments"],
            {"total": 2, "pending": 0, "evaluated": 2},
        )
        self.assertEqual(complete["solution_funnel"]["evaluated"], 1)
        self.assertEqual(complete["attention"]["projects_awaiting_evaluation"], 0)
        create_rate_criteria(self.program)
        self.assertEqual(
            self.overview()["evaluation_status"]["assignments"]["evaluated"], 0
        )

    def test_zero_criteria_or_unsubmitted_link_never_completes_assignment(self):
        self.assignment(self.link.project, self.expert)
        for criterion in self.criteria:
            self.score(self.link.project, self.expert, criterion)
        self.link.submitted = False
        self.link.save(update_fields=["submitted"])
        payload = self.overview()
        self.assertEqual(payload["evaluation_status"]["assignments"]["pending"], 1)
        self.assertEqual(payload["solution_funnel"]["evaluated"], 0)
        self.program.criterias.all().delete()
        self.link.submitted = True
        self.link.save(update_fields=["submitted"])
        self.assertEqual(
            self.overview()["evaluation_status"]["assignments"]["pending"], 1
        )

    def test_completion_does_not_require_maximum_number_of_assignments(self):
        self.assignment(self.link.project, self.expert)
        for criterion in self.criteria:
            self.score(self.link.project, self.expert, criterion)
        self.assertEqual(self.overview()["solution_funnel"]["evaluated"], 1)


class ProjectAnalyticsIsolationTests(ProjectAnalyticsFixture, TestCase):
    def manager_response(self):
        url = reverse(
            "partner_programs:manager-overview", kwargs={"program_id": self.program.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response

    def seed_production(self):
        fixture = production_tests.ManagerProgramOverviewAPITests()
        fixture.program = self.program
        fixture.seed_complete_overview(self.program, self.manager, "isolated-domain")

    def seed_legacy(self):
        project = create_project(region="Legacy region")
        create_program_project(self.program, project=project, submitted=True)
        expert = create_rate_expert(program=self.program)
        self.assignment(project, expert)
        self.score(project, expert, create_rate_criteria(self.program))

    def test_only_production_domain_keeps_legacy_project_counters_zero(self):
        self.seed_production()
        manager = self.manager_response().json()
        legacy = self.overview()
        self.assertEqual(manager["applications"]["total"], 6)
        self.assertEqual(manager["teams"]["total"], 1)
        self.assertEqual(manager["submissions"]["total"], 5)
        self.assertEqual(manager["expert_assignments"]["total"], 3)
        self.assertEqual(manager["evaluations"]["total"], 2)
        self.assertEqual(legacy["summary"]["projects"]["total"], 0)
        self.assertEqual(legacy["summary"]["participants"]["total"], 2)
        self.assertEqual(legacy["summary"]["experts"]["total"], 1)
        self.assertEqual(legacy["evaluation_status"]["assignments"]["total"], 0)
        self.assertEqual(
            sum(item["submitted_solutions"] for item in legacy["activity"]), 0
        )

    def test_only_legacy_data_does_not_change_manager_overview_bytes(self):
        before = self.manager_response().content
        self.seed_legacy()
        self.assertEqual(self.manager_response().content, before)
        self.assertEqual(self.overview()["solution_funnel"]["evaluated"], 1)

    def test_both_domains_coexist_without_changing_manager_overview_bytes(self):
        self.seed_production()
        before = self.manager_response().content
        self.seed_legacy()
        self.assertEqual(self.manager_response().content, before)
        self.assertEqual(self.overview()["solution_funnel"]["evaluated"], 1)

    def test_adding_production_application_team_submission_and_evaluation_is_independent(
        self,
    ):
        self.seed_legacy()
        user = create_user(password=None)
        expert = create_rate_expert(program=self.program).expert
        before = self.overview()
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
            submission=submission, expert=expert, assigned_by=self.manager
        )
        Evaluation.objects.create(submission=submission, expert=expert)
        self.assertEqual(self.overview(), before)

    def test_service_never_queries_production_domain_tables(self):
        self.seed_production()
        self.seed_legacy()
        with CaptureQueriesContext(connection) as queries:
            self.overview()
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


class ProjectAnalyticsContractTests(ProjectAnalyticsFixture, TestCase):
    def test_serializer_validates_without_sql_and_rejects_negative_counters(self):
        payload = self.overview()
        with self.assertNumQueries(0):
            serializer = ProjectAnalyticsSerializer(data=payload)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(serializer.data, payload)

        def counters(value, path=()):
            if isinstance(value, dict):
                for key, nested in value.items():
                    yield from counters(nested, (*path, key))
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    yield from counters(nested, (*path, index))
            elif isinstance(value, int):
                yield path

        payload["summary"]["regions"] = {
            "total": 1,
            "items": [{"name": "Region", "count": 1}],
        }
        payload["summary"]["participant_regions"] = deepcopy(
            payload["summary"]["regions"]
        )
        for path in counters(payload):
            invalid = deepcopy(payload)
            target = invalid
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = -1
            with self.subTest(path=path), self.assertNumQueries(0):
                self.assertFalse(ProjectAnalyticsSerializer(data=invalid).is_valid())

    def test_serializer_rejects_invalid_mode_zero_maximum_and_invalid_dates(self):
        payload = self.overview()
        for invalid in (
            {
                **payload,
                "evaluation_status": {
                    **payload["evaluation_status"],
                    "mode": "application",
                },
            },
            {
                **payload,
                "evaluation_status": {
                    **payload["evaluation_status"],
                    "max_evaluations_per_project": 0,
                },
            },
            {
                **payload,
                "activity": [
                    {"date": "invalid", "registrations": 0, "submitted_solutions": 0}
                ],
            },
        ):
            self.assertFalse(ProjectAnalyticsSerializer(data=invalid).is_valid())

    def test_aggregates_do_not_expose_personal_or_project_content(self):
        user = create_user(password=None)
        create_program_member(self.program, user=user, data={"secret": "Private answer"})
        project = create_project(
            leader=user, name="Private project", description="Private description"
        )
        create_program_project(self.program, project=project)
        encoded = json.dumps(self.overview())
        for value in (user.email, "Private answer", project.name, project.description):
            self.assertNotIn(value, encoded)

    def test_query_budget_is_fixed_for_empty_small_and_large_programs_in_both_modes(self):
        expert = create_rate_expert(program=self.program)
        criterion = create_rate_criteria(self.program)
        counts = {}
        for size in (0, 1, 31):
            if size:
                for index in range(1 if size == 1 else 30):
                    user = create_user(password=None, city=f"City {size}-{index}")
                    create_program_member(self.program, user=user)
                    project = create_project(leader=user, region=f"Region {size}-{index}")
                    create_program_project(self.program, project=project, submitted=True)
                    self.assignment(project, expert)
                    self.score(project, expert, criterion)
            for distributed in (False, True):
                self.program.is_distributed_evaluation = distributed
                self.program.save(update_fields=["is_distributed_evaluation"])
                self.overview()
                with CaptureQueriesContext(connection) as queries:
                    payload = self.overview()
                counts[size, distributed] = len(queries)
                self.assertEqual(payload["summary"]["participants"]["total"], size)
                self.assertEqual(payload["summary"]["projects"]["total"], size)
                self.assertEqual(
                    payload["evaluation_status"]["assignments"]["total"], size
                )
        self.assertEqual(set(counts.values()), {10}, counts)
        with self.assertNumQueries(8):
            build_project_analytics(self.program)
