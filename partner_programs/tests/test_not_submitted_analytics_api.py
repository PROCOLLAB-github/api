"""Контракт несданных связей программы: применимость, доступ и SQL-пагинация."""

from datetime import datetime, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject
from partner_programs.serializers.attention import ProgramNotSubmittedProjectSerializer
from partner_programs.services.analytics import projects_not_submitted_rows
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import ProjectExpertAssignment
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator, Project


NOW = datetime(2026, 9, 6, 12, tzinfo=datetime_timezone.utc)


class ProjectsNotSubmittedAnalyticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = create_user(prefix="not-submitted-manager")
        cls.leader = create_user(first_name="Анна", last_name="Петрова", avatar=None)
        cls.program = create_partner_program(is_competitive=True)
        cls.program.managers.add(cls.manager)
        cls.other_program = create_partner_program(is_competitive=True)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = self.url_for(self.program.pk)
        self.overview_url = reverse(
            "partner_programs:manager-overview", kwargs={"pk": self.program.pk}
        )

    def url_for(self, program_id):
        return reverse(
            "partner_programs:manager-overview-projects-not-submitted",
            kwargs={"pk": program_id},
        )

    def get(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def work(self, *, program=None, submitted=False, hours=1, **project_fields):
        project_fields.setdefault("leader", self.leader)
        link = create_program_project(
            program or self.program,
            project=create_project(**project_fields),
            submitted=submitted,
        )
        PartnerProgramProject.objects.filter(pk=link.pk).update(
            datetime_created=NOW - timedelta(hours=hours)
        )
        return link

    def test_empty_competitive_program_is_applicable_with_zero_count(self):
        data = self.get()
        self.assertTrue(data["applicable"])
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertEqual(
            self.client.get(self.overview_url).data["attention"][
                "projects_not_submitted"
            ],
            {"applicable": True, "total": 0},
        )

    def test_only_unsent_current_program_links_are_included_once(self):
        included = self.work()
        submitted = self.work(submitted=True)
        self.work(program=self.other_program, name="OtherOnlyNeedle")
        create_project(name="UnlinkedOnlyNeedle", leader=self.leader)
        create_program_project(
            self.other_program, project=included.project, submitted=True
        )
        create_program_project(
            self.other_program, project=submitted.project, submitted=False
        )
        data = self.get()
        self.assertEqual(data["count"], 1)
        self.assertEqual(
            [row["program_project_id"] for row in data["results"]], [included.pk]
        )
        self.assertEqual(self.get(search="OtherOnlyNeedle")["count"], 0)
        self.assertEqual(self.get(search="UnlinkedOnlyNeedle")["count"], 0)

    def test_draft_publicity_team_and_assignments_do_not_change_membership(self):
        expert = create_rate_expert(program=self.program)
        expected = []
        for draft in (True, False):
            for is_public in (True, False):
                link = self.work(draft=draft, is_public=is_public)
                expected.append(link.pk)
        create_program_member(self.program, user=self.manager)
        Collaborator.objects.create(project=link.project, user=self.manager, role="Test")
        ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=link.project, expert=expert.expert
        )
        self.assertEqual(self.get()["count"], 4)
        self.assertEqual(
            [row["program_project_id"] for row in self.get()["results"]], expected
        )

    def test_detail_attention_and_funnel_counts_match_in_both_evaluation_modes(self):
        for _ in range(4):
            self.work()
        self.work(submitted=True)
        for distributed in (True, False):
            with self.subTest(distributed=distributed):
                self.program.is_distributed_evaluation = distributed
                self.program.save(update_fields=["is_distributed_evaluation"])
                overview = self.client.get(self.overview_url)
                self.assertEqual(overview.status_code, 200)
                self.assertEqual(overview.data["solution_funnel"]["not_submitted"], 4)
                self.assertEqual(
                    overview.data["attention"]["projects_not_submitted"],
                    {"applicable": True, "total": self.get()["count"]},
                )
                self.assertEqual(overview.data["solution_funnel"]["submitted"], 1)

    def test_noncompetitive_unsent_links_are_not_an_attention_problem(self):
        self.work()
        self.program.is_competitive = False
        self.program.save(update_fields=["is_competitive"])
        self.assertEqual(
            self.get(),
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
        overview = self.client.get(self.overview_url).data
        self.assertEqual(overview["solution_funnel"]["not_submitted"], 1)
        self.assertEqual(
            overview["attention"]["projects_not_submitted"],
            {"applicable": False, "total": 0},
        )

    def test_funnel_units_remain_two_registered_creators_and_six_submitted_links(self):
        leaders = [self.leader, create_user()]
        for leader in leaders:
            create_program_member(self.program, user=leader)
            for _ in range(3):
                self.work(leader=leader, submitted=True)
        overview = self.client.get(self.overview_url).data
        self.assertEqual(overview["participant_funnel"]["submitted_project_creators"], 2)
        self.assertEqual(overview["solution_funnel"]["submitted"], 6)

    def test_explicit_deadline_precedes_registration_fallback(self):
        self.program.datetime_registration_ends = NOW - timedelta(days=1)
        self.program.datetime_project_submission_ends = NOW + timedelta(days=1)
        self.program.save(
            update_fields=[
                "datetime_registration_ends",
                "datetime_project_submission_ends",
            ]
        )
        with patch("partner_programs.models.timezone.now", return_value=NOW):
            data = self.get()
        self.assertEqual(
            parse_datetime(data["submission_deadline"]), NOW + timedelta(days=1)
        )
        self.assertTrue(data["submission_open"])

    def test_deadline_fallback_and_open_boundary_are_timezone_aware(self):
        for seconds, is_open in ((-1, False), (0, True), (1, True)):
            with self.subTest(seconds=seconds):
                deadline = (NOW + timedelta(seconds=seconds)).astimezone(
                    datetime_timezone(timedelta(hours=3))
                )
                self.program.datetime_project_submission_ends = None
                self.program.datetime_registration_ends = deadline
                self.program.save(
                    update_fields=[
                        "datetime_registration_ends",
                        "datetime_project_submission_ends",
                    ]
                )
                with patch("partner_programs.models.timezone.now", return_value=NOW):
                    data = self.get()
                self.assertEqual(parse_datetime(data["submission_deadline"]), deadline)
                self.assertIsNotNone(parse_datetime(data["submission_deadline"]).tzinfo)
                self.assertEqual(data["submission_open"], is_open)

    def test_past_explicit_deadline_closes_even_when_registration_is_open(self):
        self.program.datetime_project_submission_ends = NOW - timedelta(days=1)
        self.program.datetime_registration_ends = NOW + timedelta(days=1)
        self.program.save(
            update_fields=[
                "datetime_registration_ends",
                "datetime_project_submission_ends",
            ]
        )
        with patch("partner_programs.models.timezone.now", return_value=NOW):
            data = self.get()
        self.assertFalse(data["submission_open"])
        self.assertEqual(
            parse_datetime(data["submission_deadline"]), NOW - timedelta(days=1)
        )

    def test_safe_contract_and_link_date_not_project_date(self):
        link = self.work(name="Проект А")
        Project.objects.filter(pk=link.project_id).update(
            datetime_created=NOW - timedelta(days=100)
        )
        data = self.get()
        self.assertEqual(
            set(data),
            {
                "count",
                "next",
                "previous",
                "results",
                "applicable",
                "submission_deadline",
                "submission_open",
            },
        )
        item = data["results"][0]
        self.assertEqual(
            set(item), {"program_project_id", "project", "leader", "linked_at"}
        )
        self.assertEqual(item["program_project_id"], link.pk)
        self.assertEqual(item["project"], {"id": link.project_id, "name": "Проект А"})
        self.assertEqual(
            item["leader"],
            {"user_id": self.leader.pk, "full_name": "Анна Петрова", "avatar": None},
        )
        self.assertEqual(parse_datetime(item["linked_at"]), NOW - timedelta(hours=1))

    def test_empty_leader_name_has_neutral_fallback(self):
        self.leader.first_name = " "
        self.leader.last_name = ""
        self.leader.avatar = ""
        self.leader.save(update_fields=["first_name", "last_name", "avatar"])
        self.work()
        self.assertEqual(
            self.get()["results"][0]["leader"],
            {
                "user_id": self.leader.pk,
                "full_name": f"Участник №{self.leader.pk}",
                "avatar": None,
            },
        )

    def test_null_leader_contract_without_relaxing_database_schema(self):
        # Project.leader remains NOT NULL; defensive serialization alone permits null.
        link = SimpleNamespace(
            pk=1,
            project=SimpleNamespace(id=2, name="Legacy", leader=None),
            datetime_created=NOW,
        )
        with self.assertNumQueries(0):
            data = ProgramNotSubmittedProjectSerializer(link).data
        self.assertIsNone(data["leader"])

    def test_serialization_of_selected_rows_performs_no_queries(self):
        self.work()
        rows = list(projects_not_submitted_rows(self.program))
        with self.assertNumQueries(0):
            data = ProgramNotSubmittedProjectSerializer(rows, many=True).data
        self.assertEqual(len(data), 1)

    def test_trimmed_case_insensitive_search_is_applied_before_count_and_page(self):
        self.work(name="Unrelated", hours=5)
        first = self.work(name="Alpha project", hours=4)
        second = self.work(name="ALPHA second", hours=3)
        self.work(program=self.other_program, name="Alpha foreign", hours=6)
        data = self.get(search="  aLpHa  ", limit=1)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["results"][0]["program_project_id"], first.pk)
        params = parse_qs(urlparse(data["next"]).query)
        self.assertEqual(params["search"], ["  aLpHa  "])
        self.assertEqual(params["offset"], ["1"])
        page = self.get(search="alpha", limit=1, offset=1)
        self.assertEqual(page["results"][0]["program_project_id"], second.pk)
        self.assertIsNone(page["next"])
        self.assertIsNotNone(page["previous"])

    def test_search_does_not_include_leader_email_or_private_project_text(self):
        self.work(name="Public title", description="PrivateDescriptionNeedle")
        for search in (
            self.leader.email,
            self.leader.first_name,
            "PrivateDescriptionNeedle",
        ):
            with self.subTest(search=search):
                self.assertEqual(self.get(search=search)["count"], 0)
        self.assertEqual(self.get(search="   ")["count"], 1)

    def test_sort_is_link_creation_then_link_id_and_is_repeatable(self):
        newest = self.work(hours=1)
        older = self.work(hours=2)
        tied = self.work(hours=2)
        for _ in range(2):
            self.assertEqual(
                [item["program_project_id"] for item in self.get()["results"]],
                [older.pk, tied.pk, newest.pk],
            )

    def test_default_limit_max_limit_and_offset_beyond_count(self):
        for _ in range(31):
            self.work()
        first = self.get()
        self.assertEqual(first["count"], 31)
        self.assertEqual(len(first["results"]), 25)
        self.assertIsNone(first["previous"])
        self.assertIsNotNone(first["next"])
        self.assertEqual(len(self.get(limit=100)["results"]), 31)
        beyond = self.get(offset=999)
        self.assertEqual(beyond["results"], [])
        self.assertEqual(beyond["count"], 31)

    def test_invalid_pagination_returns_400_with_field_error(self):
        for field, values in (
            ("limit", (0, -1, 101, "abc", "1.5", "")),
            ("offset", (-1, "abc", "1.5", "")),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.client.get(self.url, {field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.data)

    def test_manager_staff_and_superuser_have_access(self):
        for user in (
            self.manager,
            create_user(is_staff=True),
            create_user(is_superuser=True),
        ):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.get()

    def test_anonymous_is_unauthorized(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_participant_expert_and_other_manager_cannot_access_or_search(self):
        participant = create_program_member(self.program).user
        expert = create_rate_expert(program=self.program)
        other_manager = create_user()
        self.other_program.managers.add(other_manager)
        for user in (participant, expert, other_manager, create_user()):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.assertEqual(
                    self.client.get(self.url, {"search": "Project"}).status_code, 403
                )

    def test_current_manager_cannot_read_another_program(self):
        self.assertEqual(
            self.client.get(self.url_for(self.other_program.pk)).status_code, 403
        )

    def test_missing_program_is_not_found(self):
        self.assertEqual(self.client.get(self.url_for(99999999)).status_code, 404)

    def test_write_methods_are_405_and_do_not_change_submission(self):
        link = self.work()
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url, {"submitted": True}, format="json"
                )
                self.assertEqual(response.status_code, 405)
        link.refresh_from_db()
        self.assertFalse(link.submitted)

    def test_query_count_is_constant_from_one_to_31_rows(self):
        self.work()
        with CaptureQueriesContext(connection) as small:
            self.assertEqual(self.get(limit=100)["count"], 1)
        for _ in range(30):
            self.work(leader=create_user())
        with CaptureQueriesContext(connection) as large:
            data = self.get(limit=100)
        self.assertEqual(len(data["results"]), 31)
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 4)
