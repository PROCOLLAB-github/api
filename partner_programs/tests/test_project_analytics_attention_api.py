from datetime import datetime, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.serializers.project_analytics_attention import (
    ProjectAnalyticsAwaitingProjectSerializer,
    ProjectAnalyticsNotSubmittedProjectSerializer,
    ProjectAnalyticsParticipantSerializer,
)
from partner_programs.services.project_analytics import (
    participants_without_team_rows,
    projects_awaiting_evaluation_rows,
    projects_not_submitted_rows,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator, Project

NOW = datetime(2026, 9, 10, 12, tzinfo=datetime_timezone.utc)
PARTICIPANTS = "project-analytics-participants-without-team"
AWAITING = "project-analytics-projects-awaiting-evaluation"
NOT_SUBMITTED = "project-analytics-projects-not-submitted"
ENDPOINTS = (PARTICIPANTS, AWAITING, NOT_SUBMITTED)


class ProjectAnalyticsAttentionFixture:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.manager = create_user(password=None)
        cls.program = create_partner_program(
            is_competitive=True,
            is_distributed_evaluation=True,
            max_project_rates=3,
        )
        cls.program.managers.add(cls.manager)
        cls.other_program = create_partner_program(
            is_competitive=True, is_distributed_evaluation=True
        )
        cls.expert = create_rate_expert(program=cls.program)
        cls.program.criterias.all().delete()
        cls.criteria = [
            Criteria.objects.create(
                partner_program=cls.program,
                name=f"Attention criterion {index}",
                type="int",
                min_value=0,
                max_value=10,
            )
            for index in range(2)
        ]

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def url(self, endpoint, program=None):
        return reverse(
            f"partner_programs:{endpoint}",
            kwargs={"program_id": (program or self.program).pk},
        )

    def get(self, endpoint, program=None, **params):
        response = self.client.get(self.url(endpoint, program), params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.json()

    def overview(self, program=None):
        response = self.client.get(
            reverse(
                "partner_programs:project-analytics",
                kwargs={"program_id": (program or self.program).pk},
            )
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.json()

    def participant(self, *, program=None, user=None, hours=1, **user_fields):
        user = user or create_user(password=None, **user_fields)
        profile = create_program_member(program or self.program, user=user)
        PartnerProgramUserProfile.objects.filter(pk=profile.pk).update(
            datetime_created=NOW - timedelta(hours=hours)
        )
        return profile

    def work(
        self,
        *,
        program=None,
        submitted=True,
        linked_hours=2,
        submitted_hours=1,
        project=None,
        **project_fields,
    ):
        link = create_program_project(
            program or self.program,
            project=project or create_project(**project_fields),
            submitted=submitted,
        )
        PartnerProgramProject.objects.filter(pk=link.pk).update(
            datetime_created=NOW - timedelta(hours=linked_hours),
            datetime_submitted=(
                NOW - timedelta(hours=submitted_hours) if submitted else None
            ),
        )
        return link

    def assignment(self, link, *, expert=None, program=None):
        return ProjectExpertAssignment.objects.create(
            partner_program=program or self.program,
            project=link.project,
            expert=(expert or self.expert).expert,
        )

    def score(self, link, *, expert=None, criteria=None):
        for criterion in self.criteria if criteria is None else criteria:
            ProjectScore.objects.get_or_create(
                project=link.project,
                user=expert or self.expert,
                criteria=criterion,
                defaults={"value": "0"},
            )

    def set_open_mode(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            is_distributed_evaluation=False
        )
        self.program.is_distributed_evaluation = False


class ProjectAnalyticsAttentionAccessTests(ProjectAnalyticsAttentionFixture, TestCase):
    def test_manager_staff_and_superuser_can_read_all_lists(self):
        for user in (
            self.manager,
            create_user(password=None, is_staff=True),
            create_user(password=None, is_superuser=True, is_staff=False),
        ):
            self.client.force_authenticate(user)
            for endpoint in ENDPOINTS:
                with self.subTest(user=user.pk, endpoint=endpoint):
                    self.assertEqual(self.client.get(self.url(endpoint)).status_code, 200)

    def test_participant_expert_other_manager_and_unrelated_user_get_403(self):
        participant = self.participant().user
        other_manager = create_user(password=None)
        self.other_program.managers.add(other_manager)
        for user in (
            participant,
            self.expert,
            other_manager,
            create_user(password=None),
        ):
            self.client.force_authenticate(user)
            for endpoint in ENDPOINTS:
                with self.subTest(user=user.pk, endpoint=endpoint):
                    self.assertEqual(
                        self.client.get(
                            self.url(endpoint), {"search": "Private"}
                        ).status_code,
                        403,
                    )

    def test_anonymous_gets_401_and_unknown_program_gets_404(self):
        self.client.force_authenticate(None)
        for endpoint in ENDPOINTS:
            self.assertEqual(self.client.get(self.url(endpoint)).status_code, 401)
        self.client.force_authenticate(self.manager)
        for endpoint in ENDPOINTS:
            url = reverse(f"partner_programs:{endpoint}", kwargs={"program_id": 99999999})
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_mutating_methods_are_405_and_do_not_change_links_or_profiles(self):
        profile = self.participant()
        link = self.work(submitted=False)
        for endpoint in ENDPOINTS:
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(endpoint=endpoint, method=method):
                    response = getattr(self.client, method)(
                        self.url(endpoint), {"submitted": True}, format="json"
                    )
                    self.assertEqual(response.status_code, 405)
        self.assertTrue(PartnerProgramUserProfile.objects.filter(pk=profile.pk).exists())
        link.refresh_from_db()
        self.assertFalse(link.submitted)

    def test_invalid_pagination_and_valid_empty_search_on_all_lists(self):
        for endpoint in ENDPOINTS:
            for field, values in (
                ("limit", (0, -1, 101, "abc", "1.5", "")),
                ("offset", (-1, "abc", "1.5", "")),
            ):
                for value in values:
                    with self.subTest(endpoint=endpoint, field=field, value=value):
                        response = self.client.get(self.url(endpoint), {field: value})
                        self.assertEqual(response.status_code, 400)
                        self.assertIn(field, response.data)
            self.assertEqual(
                self.get(endpoint, search="   ")["results"],
                self.get(endpoint)["results"],
            )

    def test_offset_beyond_count_preserves_count_and_returns_empty_page(self):
        self.participant()
        self.work()
        self.work(submitted=False)
        for endpoint in ENDPOINTS:
            data = self.get(endpoint, offset=999)
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["results"], [])


class ParticipantsWithoutTeamTests(ProjectAnalyticsAttentionFixture, TestCase):
    def test_only_unique_registered_users_without_current_program_team_are_listed(self):
        included = self.participant(first_name="Анна", last_name="Петрова")
        leader = self.participant().user
        collaborator = self.participant().user
        leader_link = self.work(leader=leader)
        Collaborator.objects.create(project=leader_link.project, user=collaborator)
        profile_only = self.participant()
        PartnerProgramUserProfile.objects.filter(pk=profile_only.pk).update(
            project=leader_link.project
        )
        other_only = self.participant().user
        self.participant(program=self.other_program, user=other_only)
        other_link = self.work(program=self.other_program)
        Collaborator.objects.create(project=other_link.project, user=other_only)
        PartnerProgramUserProfile.objects.create(
            partner_program=self.program, user=None, partner_program_data={}
        )
        data = self.get(PARTICIPANTS)
        self.assertEqual(data["count"], 3)
        self.assertEqual(
            {item["user_id"] for item in data["results"]},
            {included.user_id, profile_only.user_id, other_only.pk},
        )
        self.assertEqual(
            data["count"], self.overview()["attention"]["participants_without_team"]
        )

    def test_leader_counts_as_team_without_collaborator_row(self):
        profile = self.participant()
        link = self.work(leader=profile.user)
        Collaborator.objects.filter(project=link.project, user=profile.user).delete()
        self.assertEqual(self.get(PARTICIPANTS)["count"], 0)

    def test_safe_fields_fallback_name_and_current_program_registration_time(self):
        profile = self.participant(
            first_name=" ", last_name="", city=None, avatar=None, hours=10
        )
        profile.partner_program_data = {
            "email": "secret@example.com",
            "phone": "private",
        }
        profile.save(update_fields=["partner_program_data"])
        self.participant(program=self.other_program, user=profile.user, hours=100)
        type(profile.user).objects.filter(pk=profile.user_id).update(
            datetime_created=NOW - timedelta(days=365)
        )
        item = self.get(PARTICIPANTS)["results"][0]
        self.assertEqual(
            set(item), {"user_id", "full_name", "avatar", "city", "registered_at"}
        )
        self.assertEqual(item["full_name"], f"Участник №{profile.user_id}")
        self.assertIsNone(item["avatar"])
        self.assertIsNone(item["city"])
        self.assertEqual(parse_datetime(item["registered_at"]), NOW - timedelta(hours=10))

    def test_search_uses_first_last_and_full_name_but_not_private_fields(self):
        target = self.participant(
            first_name="Alice", last_name="UniqueSmith", city="SecretCity"
        )
        target.partner_program_data = {"answer": "PrivateNeedle"}
        target.save(update_fields=["partner_program_data"])
        self.participant(first_name="Bob", last_name="Jones")
        for search in (" alice ", "uniquesmith", "Alice UniqueSmith", "LIC"):
            data = self.get(PARTICIPANTS, search=search)
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["results"][0]["user_id"], target.user_id)
        for search in (target.user.email, "SecretCity", "PrivateNeedle"):
            self.assertEqual(self.get(PARTICIPANTS, search=search)["count"], 0)

    def test_stable_order_pagination_links_and_default_limit(self):
        profiles = [
            self.participant(first_name="Needle", hours=hours) for hours in (1, 2, 2)
        ]
        expected = [profiles[1].user_id, profiles[2].user_id, profiles[0].user_id]
        first = self.get(PARTICIPANTS, search=" Needle ", limit=2)
        self.assertEqual([item["user_id"] for item in first["results"]], expected[:2])
        self.assertEqual(
            parse_qs(urlparse(first["next"]).query),
            {"search": [" Needle "], "limit": ["2"], "offset": ["2"]},
        )
        second = self.get(PARTICIPANTS, search="Needle", limit=2, offset=2)
        self.assertEqual(second["results"][0]["user_id"], expected[2])
        for _ in range(23):
            self.participant()
        page = self.get(PARTICIPANTS)
        self.assertEqual(page["count"], 26)
        self.assertEqual(len(page["results"]), 25)

    def test_deleted_user_registration_is_not_disclosed(self):
        profile = self.participant()
        profile.user.delete()
        self.assertEqual(self.get(PARTICIPANTS)["count"], 0)


class ProjectsAwaitingEvaluationTests(ProjectAnalyticsAttentionFixture, TestCase):
    def test_distributed_reasons_and_completion_parity_with_assignment_list(self):
        no_assignments = self.work(name="No assignments")
        none_complete = self.work(name="None complete")
        self.assignment(none_complete)
        partial_score = self.work(name="Partial score")
        partial_assignment = self.assignment(partial_score)
        self.score(partial_score, criteria=self.criteria[:1])
        partly_evaluated = self.work(name="Partly evaluated")
        completed_assignment = self.assignment(partly_evaluated)
        self.score(partly_evaluated)
        self.assignment(partly_evaluated, expert=create_rate_expert(program=self.program))
        fully_evaluated = self.work(name="Fully evaluated")
        final_assignment = self.assignment(fully_evaluated)
        self.score(fully_evaluated)

        data = self.get(AWAITING, limit=100)
        self.assertEqual(data["mode"], "distributed")
        by_id = {item["program_project_id"]: item for item in data["results"]}
        self.assertEqual(
            set(by_id),
            {no_assignments.pk, none_complete.pk, partial_score.pk, partly_evaluated.pk},
        )
        self.assertEqual(
            (
                by_id[no_assignments.pk]["reason"],
                by_id[no_assignments.pk]["reason_label"],
            ),
            ("no_assignments", "Эксперты не назначены"),
        )
        for link in (none_complete, partial_score):
            self.assertEqual(by_id[link.pk]["status"], "awaiting_evaluation")
            self.assertEqual(by_id[link.pk]["reason"], "no_completed_evaluations")
            self.assertEqual(by_id[link.pk]["reason_label"], "Нет завершённых оценок")
        self.assertEqual(by_id[partly_evaluated.pk]["status"], "partially_evaluated")
        self.assertEqual(by_id[partly_evaluated.pk]["reason"], "partially_evaluated")
        self.assertEqual(by_id[partly_evaluated.pk]["reason_label"], "Частично оценено")

        assignments = self.client.get(
            reverse(
                "partner_programs:project-analytics-assignments",
                kwargs={"program_id": self.program.pk},
            )
        ).json()
        status_by_assignment = {
            item["assignment_id"]: item["status"] for item in assignments
        }
        self.assertEqual(status_by_assignment[partial_assignment.pk], "in_progress")
        self.assertEqual(status_by_assignment[completed_assignment.pk], "completed")
        self.assertEqual(status_by_assignment[final_assignment.pk], "completed")
        self.assertEqual(
            by_id[partly_evaluated.pk]["assignments_completed"],
            sum(
                status_by_assignment[item.pk] == "completed"
                for item in ProjectExpertAssignment.objects.filter(
                    partner_program=self.program, project=partly_evaluated.project
                )
            ),
        )
        self.assertEqual(
            data["count"], self.overview()["attention"]["projects_awaiting_evaluation"]
        )

    def test_zero_criteria_foreign_scores_and_maximum_do_not_complete(self):
        link = self.work()
        self.assignment(link)
        other_expert = create_rate_expert(program=self.program)
        self.score(link, expert=other_expert)
        foreign = Criteria.objects.create(
            partner_program=self.other_program, name="Foreign", type="str"
        )
        self.score(link, criteria=[foreign])
        PartnerProgram.objects.filter(pk=self.program.pk).update(max_project_rates=1)
        self.assertEqual(self.get(AWAITING)["results"][0]["assignments_completed"], 0)
        self.program.criterias.all().delete()
        self.assertEqual(
            self.get(AWAITING)["results"][0]["reason"],
            "no_completed_evaluations",
        )

    def test_open_mode_uses_first_current_program_score_and_null_progress(self):
        self.set_open_mode()
        waiting = self.work(name="Waiting")
        evaluated = self.work(name="Evaluated")
        self.score(evaluated, criteria=self.criteria[:1])
        foreign_score = self.work(name="Foreign score")
        foreign = Criteria.objects.create(
            partner_program=self.other_program, name="Foreign", type="str"
        )
        self.score(foreign_score, criteria=[foreign])
        self.assignment(waiting)
        data = self.get(AWAITING)
        self.assertEqual(data["mode"], "open")
        by_id = {item["program_project_id"]: item for item in data["results"]}
        self.assertEqual(set(by_id), {waiting.pk, foreign_score.pk})
        for item in by_id.values():
            self.assertEqual(item["status"], "awaiting_evaluation")
            self.assertEqual(item["reason"], "awaiting_first_evaluation")
            self.assertEqual(item["reason_label"], "Ожидает первой оценки")
            self.assertIsNone(item["assignments_total"])
            self.assertIsNone(item["assignments_completed"])

    def test_unsubmitted_and_not_ready_are_excluded(self):
        link = self.work(submitted=False)
        self.assignment(link)
        self.score(link)
        self.assertEqual(self.get(AWAITING)["count"], 0)

    def test_safe_contract_search_and_order_use_project_and_submission_only(self):
        leader = create_user(
            password=None, first_name="Анна", last_name="Иванова", avatar=None
        )
        newest = self.work(leader=leader, name="Unique Project", submitted_hours=1)
        older = self.work(name="Other", description="Unique Project", submitted_hours=2)
        tied = self.work(name="Third", submitted_hours=2)
        unknown = self.work(name="Unknown", submitted_hours=3)
        PartnerProgramProject.objects.filter(pk=unknown.pk).update(
            datetime_submitted=None
        )
        data = self.get(AWAITING, search=" UNIQUE ")
        self.assertEqual(data["count"], 1)
        item = data["results"][0]
        self.assertEqual(
            set(item),
            {
                "program_project_id",
                "project",
                "leader",
                "submitted_at",
                "status",
                "reason",
                "reason_label",
                "assignments_total",
                "assignments_completed",
            },
        )
        self.assertEqual(
            item["project"], {"id": newest.project_id, "name": "Unique Project"}
        )
        self.assertEqual(
            item["leader"],
            {"user_id": leader.pk, "full_name": "Анна Иванова", "avatar": None},
        )
        self.assertEqual(self.get(AWAITING, search=leader.email)["count"], 0)
        self.assertEqual(
            [item["program_project_id"] for item in self.get(AWAITING)["results"]],
            [older.pk, tied.pk, newest.pk, unknown.pk],
        )

    def test_multi_program_submission_assignment_criteria_and_score_are_independent(self):
        shared = create_project()
        link_a = self.work(project=shared, submitted=False)
        link_b = self.work(program=self.other_program, project=shared, submitted=True)
        other_expert = create_rate_expert(program=self.other_program)
        ProjectExpertAssignment.objects.create(
            partner_program=self.other_program,
            project=shared,
            expert=other_expert.expert,
        )
        other_criterion = self.other_program.criterias.order_by("pk").first()
        ProjectScore.objects.create(
            project=shared,
            user=other_expert,
            criteria=other_criterion,
            value="done",
        )
        self.assertEqual(self.get(AWAITING)["count"], 0)
        self.other_program.managers.add(self.manager)
        other_data = self.get(AWAITING, program=self.other_program)
        self.assertEqual(other_data["count"], 0)
        PartnerProgramProject.objects.filter(pk=link_a.pk).update(submitted=True)
        self.assertEqual(
            self.get(AWAITING)["results"][0]["program_project_id"], link_a.pk
        )
        self.assertNotEqual(link_a.pk, link_b.pk)

    def test_defensive_null_leader_serialization_is_sql_free(self):
        link = SimpleNamespace(
            pk=1,
            project=SimpleNamespace(id=2, name="Legacy", leader=None),
            datetime_submitted=None,
            status="awaiting_evaluation",
            reason="no_assignments",
            assignments_total=0,
            assignments_completed=0,
        )
        with self.assertNumQueries(0):
            payload = ProjectAnalyticsAwaitingProjectSerializer(link).data
        self.assertIsNone(payload["leader"])
        self.assertIsNone(payload["submitted_at"])


class ProjectsNotSubmittedTests(ProjectAnalyticsAttentionFixture, TestCase):
    def test_competitive_list_uses_raw_current_program_links_and_matches_overview(self):
        included = self.work(submitted=False, draft=True, is_public=False)
        self.work(submitted=True)
        self.work(program=self.other_program, submitted=False, name="Foreign")
        create_program_project(
            self.other_program, project=included.project, submitted=True
        )
        data = self.get(NOT_SUBMITTED)
        self.assertTrue(data["applicable"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["program_project_id"], included.pk)
        overview = self.overview()
        self.assertEqual(data["count"], overview["solution_funnel"]["not_submitted"])
        self.assertEqual(
            overview["attention"]["projects_not_submitted"],
            {"applicable": True, "total": data["count"]},
        )

    def test_noncompetitive_is_not_applicable_without_changing_raw_funnel(self):
        self.work(submitted=False)
        PartnerProgram.objects.filter(pk=self.program.pk).update(is_competitive=False)
        self.program.is_competitive = False
        self.assertEqual(
            self.get(NOT_SUBMITTED),
            {
                "count": 0,
                "next": None,
                "previous": None,
                "results": [],
                "applicable": False,
                "submission_deadline": None,
                "submission_open": False,
            },
        )
        overview = self.overview()
        self.assertEqual(overview["solution_funnel"]["not_submitted"], 1)
        self.assertEqual(
            overview["attention"]["projects_not_submitted"],
            {"applicable": False, "total": 0},
        )

    def test_deadline_and_open_metadata_use_program_methods(self):
        for explicit, registration, expected, is_open in (
            (
                NOW + timedelta(days=1),
                NOW - timedelta(days=1),
                NOW + timedelta(days=1),
                True,
            ),
            (
                NOW - timedelta(seconds=1),
                NOW + timedelta(days=1),
                NOW - timedelta(seconds=1),
                False,
            ),
            (None, NOW, NOW, True),
        ):
            self.program.datetime_project_submission_ends = explicit
            self.program.datetime_registration_ends = registration
            PartnerProgram.objects.filter(pk=self.program.pk).update(
                datetime_project_submission_ends=explicit,
                datetime_registration_ends=registration,
            )
            with self.subTest(explicit=explicit):
                with patch("partner_programs.models.timezone.now", return_value=NOW):
                    data = self.get(NOT_SUBMITTED)
                self.assertEqual(parse_datetime(data["submission_deadline"]), expected)
                self.assertEqual(data["submission_open"], is_open)

    def test_safe_contract_link_date_search_scope_and_stable_order(self):
        leader = create_user(
            password=None, first_name="Анна", last_name="Петрова", avatar=None
        )
        newest = self.work(
            submitted=False, leader=leader, name="Unique Project", linked_hours=1
        )
        older = self.work(
            submitted=False,
            name="Other",
            description="Unique Project",
            linked_hours=2,
        )
        tied = self.work(submitted=False, name="Third", linked_hours=2)
        data = self.get(NOT_SUBMITTED, search=" UNIQUE ")
        self.assertEqual(data["count"], 1)
        item = data["results"][0]
        self.assertEqual(
            set(item), {"program_project_id", "project", "leader", "linked_at"}
        )
        self.assertEqual(
            item["project"], {"id": newest.project_id, "name": "Unique Project"}
        )
        self.assertEqual(
            item["leader"],
            {"user_id": leader.pk, "full_name": "Анна Петрова", "avatar": None},
        )
        project_created = NOW - timedelta(days=100)
        Project.objects.filter(pk=newest.project_id).update(
            datetime_created=project_created
        )
        self.assertEqual(parse_datetime(item["linked_at"]), NOW - timedelta(hours=1))
        for search in (leader.first_name, leader.email, "Unique Project"):
            count = self.get(NOT_SUBMITTED, search=search)["count"]
            self.assertEqual(count, int(search == "Unique Project"))
        self.assertEqual(
            [item["program_project_id"] for item in self.get(NOT_SUBMITTED)["results"]],
            [older.pk, tied.pk, newest.pk],
        )

    def test_pagination_preserves_search_and_supports_limit_100(self):
        links = [
            self.work(submitted=False, name="Needle", linked_hours=hours)
            for hours in range(31, 0, -1)
        ]
        first = self.get(NOT_SUBMITTED, search=" Needle ", limit=25)
        self.assertEqual(first["count"], 31)
        self.assertEqual(len(first["results"]), 25)
        self.assertEqual(
            parse_qs(urlparse(first["next"]).query),
            {"search": [" Needle "], "limit": ["25"], "offset": ["25"]},
        )
        self.assertEqual(len(self.get(NOT_SUBMITTED, limit=100)["results"]), 31)
        self.assertEqual(first["results"][0]["program_project_id"], links[0].pk)

    def test_defensive_null_leader_serializer_does_no_sql(self):
        link = SimpleNamespace(
            pk=1,
            project=SimpleNamespace(id=2, name="Legacy", leader=None),
            datetime_created=NOW,
        )
        with self.assertNumQueries(0):
            payload = ProjectAnalyticsNotSubmittedProjectSerializer(link).data
        self.assertIsNone(payload["leader"])


class ProjectAnalyticsAttentionQueryTests(ProjectAnalyticsAttentionFixture, TestCase):
    def test_serializers_do_no_sql_for_selected_rows(self):
        self.participant()
        submitted = self.work()
        draft = self.work(submitted=False)
        fixtures = (
            (
                participants_without_team_rows(self.program.pk),
                ProjectAnalyticsParticipantSerializer,
            ),
            (
                projects_awaiting_evaluation_rows(self.program),
                ProjectAnalyticsAwaitingProjectSerializer,
            ),
            (
                projects_not_submitted_rows(self.program),
                ProjectAnalyticsNotSubmittedProjectSerializer,
            ),
        )
        self.assertTrue(submitted.pk and draft.pk)
        for queryset, serializer_class in fixtures:
            rows = list(queryset)
            with self.subTest(
                serializer=serializer_class.__name__
            ), self.assertNumQueries(0):
                self.assertEqual(len(serializer_class(rows, many=True).data), 1)

    def test_each_endpoint_has_fixed_four_queries_for_one_and_thirty_one_rows(self):
        self.participant(first_name="Scale")
        self.work(name="Scale")
        self.work(submitted=False, name="Scale")
        small = {}
        for endpoint in ENDPOINTS:
            with CaptureQueriesContext(connection) as queries:
                self.get(endpoint, limit=100, search="Scale")
            small[endpoint] = len(queries)
        for _ in range(30):
            self.participant(first_name="Scale")
            self.work(name="Scale")
            self.work(submitted=False, name="Scale")
        for endpoint in ENDPOINTS:
            with CaptureQueriesContext(connection) as queries:
                data = self.get(endpoint, limit=100, search="Scale")
            self.assertEqual(data["count"], 31)
            self.assertEqual(len(data["results"]), 31)
            self.assertEqual(len(queries), small[endpoint])
            self.assertEqual(len(queries), 4)
