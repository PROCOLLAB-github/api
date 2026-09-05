from datetime import datetime, timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.serializers.attention import ProgramAttentionProjectSerializer
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


NOW = datetime(2026, 9, 5, 12, tzinfo=datetime_timezone.utc)
PARTICIPANTS = "manager-overview-participants-without-team"
PROJECTS = "manager-overview-projects-awaiting-evaluation"


class AttentionAnalyticsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = create_user(prefix="attention-manager")
        cls.program = create_partner_program(
            is_distributed_evaluation=True, max_project_rates=3
        )
        cls.program.managers.add(cls.manager)
        cls.other_program = create_partner_program(is_distributed_evaluation=True)
        cls.expert = create_rate_expert(program=cls.program)
        # Program creation adds a comment criterion. Isolate two explicit criteria.
        Criteria.objects.filter(partner_program=cls.program).delete()
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
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def url(self, endpoint, program=None):
        return reverse(
            "partner_programs:" + endpoint,
            kwargs={"pk": (program or self.program).pk},
        )

    def get(self, endpoint, **params):
        response = self.client.get(self.url(endpoint), params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def participant(self, *, program=None, user=None, hours=1, **user_fields):
        user = user or create_user(prefix="attention-participant", **user_fields)
        registration = create_program_member(program or self.program, user=user)
        PartnerProgramUserProfile.objects.filter(pk=registration.pk).update(
            datetime_created=NOW - timedelta(hours=hours)
        )
        return registration

    def work(self, *, program=None, submitted=True, hours=1, **project_fields):
        link = create_program_project(
            program or self.program,
            project=create_project(**project_fields),
            submitted=submitted,
        )
        PartnerProgramProject.objects.filter(pk=link.pk).update(
            datetime_submitted=(NOW - timedelta(hours=hours)) if submitted else None
        )
        return link

    def assignment(self, link, expert=None, program=None):
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

    def open_mode(self):
        self.program.is_distributed_evaluation = False
        self.program.save(update_fields=["is_distributed_evaluation"])

    def assert_matches_overview(self, endpoint, metric):
        self.assertEqual(
            self.get(endpoint)["count"],
            self.get("manager-overview")["attention"][metric],
        )


class AttentionAnalyticsAccessAndPaginationTests(AttentionAnalyticsTestCase):
    def test_manager_has_access_to_both_lists(self):
        for endpoint in (PARTICIPANTS, PROJECTS):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.get(endpoint)["results"], [])

    def test_staff_and_superuser_have_access_to_both_lists(self):
        for permission in ("is_staff", "is_superuser"):
            user = create_user(prefix=f"attention-{permission}", **{permission: True})
            self.client.force_authenticate(user)
            for endpoint in (PARTICIPANTS, PROJECTS):
                with self.subTest(permission=permission, endpoint=endpoint):
                    self.get(endpoint)

    def test_anonymous_get_is_unauthorized(self):
        self.client.force_authenticate(None)
        for endpoint in (PARTICIPANTS, PROJECTS):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(self.url(endpoint)).status_code, 401)

    def test_participant_get_is_forbidden(self):
        participant = self.participant().user
        self.client.force_authenticate(participant)
        for endpoint in (PARTICIPANTS, PROJECTS):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(self.url(endpoint)).status_code, 403)

    def test_program_expert_get_is_forbidden(self):
        self.client.force_authenticate(self.expert)
        for endpoint in (PARTICIPANTS, PROJECTS):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(self.url(endpoint)).status_code, 403)

    def test_manager_of_another_program_cannot_access_or_search_lists(self):
        for endpoint in (PARTICIPANTS, PROJECTS):
            with self.subTest(endpoint=endpoint):
                response = self.client.get(
                    self.url(endpoint, self.other_program), {"search": "Program"}
                )
                self.assertEqual(response.status_code, 403)

    def test_missing_program_is_not_found(self):
        for endpoint in (PARTICIPANTS, PROJECTS):
            with self.subTest(endpoint=endpoint):
                url = reverse("partner_programs:" + endpoint, kwargs={"pk": 99999999})
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_modifying_methods_are_not_allowed_and_leave_data_unchanged(self):
        registration = self.participant()
        link = self.work()
        for endpoint in (PARTICIPANTS, PROJECTS):
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(endpoint=endpoint, method=method):
                    response = getattr(self.client, method)(
                        self.url(endpoint), {"submitted": False}, format="json"
                    )
                    self.assertEqual(response.status_code, 405)
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(pk=registration.pk).exists()
        )
        link.refresh_from_db()
        self.assertTrue(link.submitted)

    def test_invalid_pagination_is_rejected_on_both_endpoints(self):
        for endpoint in (PARTICIPANTS, PROJECTS):
            for params in (
                {"limit": "invalid"},
                {"limit": "1.5"},
                {"limit": ""},
                {"limit": 0},
                {"limit": -1},
                {"limit": 101},
                {"offset": "invalid"},
                {"offset": "1.5"},
                {"offset": ""},
                {"offset": -1},
            ):
                with self.subTest(endpoint=endpoint, params=params):
                    self.assertEqual(
                        self.client.get(self.url(endpoint), params).status_code, 400
                    )

    def test_empty_page_has_standard_pagination_envelope(self):
        for endpoint in (PARTICIPANTS, PROJECTS):
            with self.subTest(endpoint=endpoint):
                data = self.get(endpoint)
                expected = {"count", "next", "previous", "results"}
                if endpoint == PROJECTS:
                    expected.add("mode")
                self.assertEqual(set(data), expected)
                self.assertEqual(data["count"], 0)
                self.assertIsNone(data["next"])
                self.assertIsNone(data["previous"])

    def test_offset_beyond_total_returns_empty_page_without_losing_count(self):
        self.participant()
        self.work()
        for endpoint in (PARTICIPANTS, PROJECTS):
            with self.subTest(endpoint=endpoint):
                data = self.get(endpoint, offset=100)
                self.assertEqual(data["count"], 1)
                self.assertEqual(data["results"], [])

    def test_empty_search_matches_absent_search(self):
        self.participant()
        self.work()
        for endpoint in (PARTICIPANTS, PROJECTS):
            for query in ("", "   ", "\t"):
                with self.subTest(endpoint=endpoint, query=query):
                    self.assertEqual(
                        self.get(endpoint, search=query)["results"],
                        self.get(endpoint)["results"],
                    )


class ParticipantsWithoutTeamTests(AttentionAnalyticsTestCase):
    def test_registered_participant_without_team_is_included(self):
        registration = self.participant()
        data = self.get(PARTICIPANTS)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["user_id"], registration.user_id)

    def test_leader_without_collaborator_is_excluded(self):
        registration = self.participant()
        link = self.work(leader=registration.user)
        # The project creation signal adds its leader as collaborator automatically.
        Collaborator.objects.filter(project=link.project, user=registration.user).delete()
        self.assertEqual(self.get(PARTICIPANTS)["count"], 0)
        self.assert_matches_overview(PARTICIPANTS, "participants_without_team")

    def test_collaborator_without_leader_role_is_excluded(self):
        registration = self.participant()
        link = self.work()
        Collaborator.objects.create(project=link.project, user=registration.user)
        self.assertNotEqual(link.project.leader_id, registration.user_id)
        self.assertEqual(self.get(PARTICIPANTS)["count"], 0)

    def test_team_only_in_other_program_does_not_exclude_participant(self):
        registration = self.participant()
        self.participant(program=self.other_program, user=registration.user)
        link = self.work(program=self.other_program)
        Collaborator.objects.create(project=link.project, user=registration.user)
        self.assertEqual(
            self.get(PARTICIPANTS)["results"][0]["user_id"], registration.user_id
        )

    def test_leading_unlinked_project_does_not_exclude_participant(self):
        registration = self.participant()
        create_project(leader=registration.user)
        self.assertEqual(self.get(PARTICIPANTS)["count"], 1)

    def test_registration_project_field_is_not_evidence_of_team_membership(self):
        registration = self.participant()
        link = self.work()
        PartnerProgramUserProfile.objects.filter(pk=registration.pk).update(
            project=link.project
        )
        self.assertEqual(self.get(PARTICIPANTS)["count"], 1)

    def test_team_in_unsubmitted_draft_project_still_excludes_participant(self):
        registration = self.participant()
        self.work(leader=registration.user, submitted=False, draft=True)
        self.assertEqual(self.get(PARTICIPANTS)["count"], 0)

    def test_registration_in_other_program_is_not_disclosed(self):
        self.participant(program=self.other_program, first_name="UniqueOther")
        self.assertEqual(self.get(PARTICIPANTS)["count"], 0)
        self.assertEqual(self.get(PARTICIPANTS, search="UniqueOther")["count"], 0)

    def test_deleted_user_registration_is_excluded(self):
        registration = self.participant()
        registration.user.delete()
        registration.refresh_from_db()
        self.assertIsNone(registration.user_id)
        self.assertEqual(self.get(PARTICIPANTS)["count"], 0)

    def test_duplicate_registration_is_prevented_by_existing_schema(self):
        registration = self.participant()
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_program_member(self.program, user=registration.user)
        self.assertEqual(self.get(PARTICIPANTS)["count"], 1)

    def test_registered_at_uses_current_program_not_account_or_other_program_date(self):
        registration = self.participant(hours=10)
        self.participant(program=self.other_program, user=registration.user, hours=100)
        type(registration.user).objects.filter(pk=registration.user_id).update(
            datetime_created=NOW - timedelta(days=365)
        )
        item = self.get(PARTICIPANTS)["results"][0]
        self.assertEqual(parse_datetime(item["registered_at"]), NOW - timedelta(hours=10))

    def test_safe_participant_fields_and_missing_display_values(self):
        registration = self.participant(
            first_name="", last_name="", city=None, avatar=None
        )
        registration.partner_program_data = {
            "email": "secret@example.com",
            "phone": "secret",
        }
        registration.save(update_fields=["partner_program_data"])
        item = self.get(PARTICIPANTS)["results"][0]
        self.assertEqual(
            set(item), {"user_id", "full_name", "avatar", "city", "registered_at"}
        )
        self.assertEqual(item["full_name"], f"Участник №{registration.user_id}")
        self.assertIsNone(item["avatar"])
        self.assertIsNone(item["city"])

    def test_actual_name_avatar_and_legacy_city_are_preserved(self):
        self.participant(
            first_name="Анна",
            last_name="Петрова",
            city="Набережные Челны",
            avatar="https://example.com/avatar.png",
        )
        item = self.get(PARTICIPANTS)["results"][0]
        self.assertEqual(item["full_name"], "Анна Петрова")
        self.assertEqual(item["city"], "Набережные Челны")
        self.assertEqual(item["avatar"], "https://example.com/avatar.png")

    def test_count_equals_overview_for_mixed_memberships_and_null_users(self):
        self.participant()
        leader = self.participant().user
        teammate = self.participant().user
        link = self.work(leader=leader)
        Collaborator.objects.create(project=link.project, user=teammate)
        self.participant(program=self.other_program)
        PartnerProgramUserProfile.objects.create(
            partner_program=self.program, user=None, partner_program_data={}
        )
        self.assertEqual(self.get(PARTICIPANTS)["count"], 1)
        self.assert_matches_overview(PARTICIPANTS, "participants_without_team")

    def test_search_is_trimmed_case_insensitive_and_matches_both_name_parts(self):
        registration = self.participant(first_name="Alice", last_name="UniqueSmith")
        self.participant(first_name="Bob", last_name="Jones")
        for search in (" alice ", "uniquesmith", "LIC"):
            with self.subTest(search=search):
                data = self.get(PARTICIPANTS, search=search)
                self.assertEqual(data["count"], 1)
                self.assertEqual(data["results"][0]["user_id"], registration.user_id)

    def test_postgresql_cyrillic_search_is_case_insensitive(self):
        if connection.vendor != "postgresql":
            self.skipTest("Unicode icontains is verified on PostgreSQL, not SQLite LIKE")
        registration = self.participant(first_name="Анна", last_name="Петрова")
        for search in ("АННА", "анна", "ПеТрОвА"):
            with self.subTest(search=search):
                self.assertEqual(
                    self.get(PARTICIPANTS, search=search)["results"][0]["user_id"],
                    registration.user_id,
                )

    def test_search_does_not_use_email_city_or_private_registration_answers(self):
        registration = self.participant(city="UniqueNeedle")
        registration.partner_program_data = {"answer": "UniqueNeedle"}
        registration.save(update_fields=["partner_program_data"])
        for search in ("UniqueNeedle", registration.user.email):
            with self.subTest(search=search):
                self.assertEqual(self.get(PARTICIPANTS, search=search)["count"], 0)

    def test_stable_sort_is_oldest_registration_then_user_id(self):
        first = self.participant(hours=1)
        second = self.participant(hours=2)
        third = self.participant(hours=2)
        expected = [second.user_id, third.user_id, first.user_id]
        for _ in range(2):
            self.assertEqual(
                [item["user_id"] for item in self.get(PARTICIPANTS)["results"]], expected
            )

    def test_default_page_size_and_search_before_pagination(self):
        for _ in range(25):
            self.participant(hours=2)
        target = self.participant(first_name="Needle", hours=1)
        first_page = self.get(PARTICIPANTS)
        self.assertEqual(first_page["count"], 26)
        self.assertEqual(len(first_page["results"]), 25)
        self.assertNotIn(
            target.user_id, [item["user_id"] for item in first_page["results"]]
        )
        data = self.get(PARTICIPANTS, search="Needle")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["user_id"], target.user_id)

    def test_pagination_links_preserve_search_and_page_boundaries(self):
        registrations = [self.participant(first_name="Needle", hours=2) for _ in range(3)]
        first = self.get(PARTICIPANTS, search="Needle", limit=2)
        next_query = parse_qs(urlparse(first["next"]).query)
        self.assertEqual(
            next_query, {"search": ["Needle"], "limit": ["2"], "offset": ["2"]}
        )
        second = self.get(PARTICIPANTS, search="Needle", limit=2, offset=2)
        self.assertEqual(second["results"][0]["user_id"], registrations[-1].user_id)
        self.assertIsNone(second["next"])
        self.assertIsNotNone(second["previous"])

    def test_query_count_is_constant_when_participant_page_grows(self):
        self.participant()
        with CaptureQueriesContext(connection) as small:
            self.get(PARTICIPANTS, limit=100)
        for _ in range(30):
            self.participant()
        with CaptureQueriesContext(connection) as large:
            data = self.get(PARTICIPANTS, limit=100)
        self.assertEqual(len(data["results"]), 31)
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 4)


class ProjectsAwaitingEvaluationTests(AttentionAnalyticsTestCase):
    def test_distributed_submitted_without_assignments_has_explicit_reason(self):
        link = self.work()
        data = self.get(PROJECTS)
        self.assertEqual(data["mode"], "distributed")
        item = data["results"][0]
        self.assertEqual(item["program_project_id"], link.pk)
        self.assertEqual(item["status"], "awaiting_evaluation")
        self.assertEqual(item["reason"], "no_assignments")
        self.assertEqual(item["reason_label"], "Эксперты не назначены")
        self.assertEqual(item["assignments_total"], 0)
        self.assertEqual(item["assignments_completed"], 0)

    def test_assignments_without_scores_have_no_completed_evaluations_reason(self):
        self.assignment(self.work())
        item = self.get(PROJECTS)["results"][0]
        self.assertEqual(item["reason"], "no_completed_evaluations")
        self.assertEqual(item["reason_label"], "Нет завершённых оценок")
        self.assertEqual(item["assignments_total"], 1)
        self.assertEqual(item["assignments_completed"], 0)

    def test_partial_criteria_do_not_mean_completed_assignment(self):
        link = self.work()
        self.assignment(link)
        self.score(link, criteria=self.criteria[:1])
        item = self.get(PROJECTS)["results"][0]
        self.assertEqual(item["status"], "awaiting_evaluation")
        self.assertEqual(item["reason"], "no_completed_evaluations")
        self.assertEqual(item["assignments_completed"], 0)

    def test_one_complete_assignment_of_three_is_partially_evaluated(self):
        link = self.work()
        self.assignment(link)
        for _ in range(2):
            self.assignment(link, expert=create_rate_expert(program=self.program))
        self.score(link)
        item = self.get(PROJECTS)["results"][0]
        self.assertEqual(item["status"], "partially_evaluated")
        self.assertEqual(item["reason"], "partially_evaluated")
        self.assertEqual(item["reason_label"], "Частично оценено")
        self.assertEqual(item["assignments_total"], 3)
        self.assertEqual(item["assignments_completed"], 1)

    def test_all_assignments_completed_excludes_work(self):
        link = self.work()
        self.assignment(link)
        self.score(link)
        self.assertEqual(self.get(PROJECTS)["count"], 0)
        self.assert_matches_overview(PROJECTS, "projects_awaiting_evaluation")

    def test_maximum_is_not_required_number_of_completed_assignments(self):
        self.program.max_project_rates = 10
        # Keep the isolated two-criterion fixture: program.save() recreates Comment.
        type(self.program).objects.filter(pk=self.program.pk).update(max_project_rates=10)
        link = self.work()
        self.assignment(link)
        self.score(link)
        self.assertEqual(self.get(PROJECTS)["count"], 0)

    def test_unsubmitted_work_and_not_ready_assignments_are_excluded(self):
        link = self.work(submitted=False)
        self.assignment(link)
        self.score(link)
        self.assertEqual(self.get(PROJECTS)["count"], 0)

    def test_zero_criteria_does_not_complete_assignment(self):
        Criteria.objects.filter(partner_program=self.program).delete()
        self.assignment(self.work())
        item = self.get(PROJECTS)["results"][0]
        self.assertEqual(item["assignments_completed"], 0)
        self.assertEqual(item["reason"], "no_completed_evaluations")

    def test_scores_of_other_expert_cannot_complete_current_assignment(self):
        link = self.work()
        self.assignment(link)
        self.score(link, expert=create_rate_expert(program=self.program))
        self.assertEqual(self.get(PROJECTS)["results"][0]["assignments_completed"], 0)

    def test_scores_of_other_program_cannot_complete_current_assignment(self):
        link = self.work()
        self.assignment(link)
        criterion = Criteria.objects.create(
            partner_program=self.other_program, name="Other criterion", type="int"
        )
        self.score(link, criteria=[criterion])
        self.assertEqual(self.get(PROJECTS)["results"][0]["assignments_completed"], 0)

    def test_scores_of_other_project_cannot_complete_current_assignment(self):
        self.assignment(self.work())
        self.score(self.work())
        self.assertTrue(
            all(
                item["assignments_completed"] == 0
                for item in self.get(PROJECTS)["results"]
            )
        )

    def test_other_program_assignment_on_same_project_is_ignored(self):
        link = self.work()
        create_program_project(self.other_program, project=link.project, submitted=True)
        other_expert = create_rate_expert(program=self.other_program)
        self.assignment(link, expert=other_expert, program=self.other_program)
        item = self.get(PROJECTS)["results"][0]
        self.assertEqual(item["assignments_total"], 0)
        self.assertEqual(item["reason"], "no_assignments")

    def test_many_assignments_produce_only_one_program_project_row(self):
        link = self.work()
        self.assignment(link)
        for _ in range(2):
            self.assignment(link, expert=create_rate_expert(program=self.program))
        data = self.get(PROJECTS)
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["assignments_total"], 3)

    def test_open_without_scores_has_null_assignment_aggregates(self):
        self.open_mode()
        self.work()
        data = self.get(PROJECTS)
        self.assertEqual(data["mode"], "open")
        item = data["results"][0]
        self.assertEqual(item["status"], "awaiting_evaluation")
        self.assertEqual(item["reason"], "awaiting_first_evaluation")
        self.assertEqual(item["reason_label"], "Ожидает первой оценки")
        self.assertIsNone(item["assignments_total"])
        self.assertIsNone(item["assignments_completed"])
        self.assertFalse(
            ProjectExpertAssignment.objects.filter(partner_program=self.program).exists()
        )

    def test_open_first_program_criterion_score_excludes_work_without_assignment(self):
        self.open_mode()
        link = self.work()
        self.score(link, criteria=self.criteria[:1])
        self.assertEqual(self.get(PROJECTS)["count"], 0)
        self.assert_matches_overview(PROJECTS, "projects_awaiting_evaluation")

    def test_open_other_program_score_does_not_exclude_work(self):
        self.open_mode()
        link = self.work()
        criterion = Criteria.objects.create(
            partner_program=self.other_program, name="Other open criterion", type="int"
        )
        self.score(link, criteria=[criterion])
        self.assertEqual(self.get(PROJECTS)["count"], 1)

    def test_open_zero_criteria_still_waits_for_first_evaluation(self):
        self.open_mode()
        Criteria.objects.filter(partner_program=self.program).delete()
        self.work()
        self.assertEqual(
            self.get(PROJECTS)["results"][0]["reason"], "awaiting_first_evaluation"
        )

    def test_open_existing_assignment_does_not_create_progress_requirement(self):
        self.open_mode()
        link = self.work()
        self.assignment(link)
        item = self.get(PROJECTS)["results"][0]
        self.assertIsNone(item["assignments_total"])
        self.score(link, criteria=self.criteria[:1])
        self.assertEqual(self.get(PROJECTS)["count"], 0)

    def test_work_must_be_submitted_in_current_program(self):
        link = self.work(submitted=False)
        create_program_project(self.other_program, project=link.project, submitted=True)
        self.work(program=self.other_program, name="OtherOnlyNeedle")
        self.assertEqual(self.get(PROJECTS)["count"], 0)
        self.assertEqual(self.get(PROJECTS, search="OtherOnlyNeedle")["count"], 0)

    def test_legacy_submitted_without_date_keeps_null(self):
        link = self.work()
        PartnerProgramProject.objects.filter(pk=link.pk).update(datetime_submitted=None)
        self.assertIsNone(self.get(PROJECTS)["results"][0]["submitted_at"])

    def test_project_and_leader_contract_has_only_safe_minimal_fields(self):
        leader = create_user(first_name="Анна", last_name="Иванова", avatar=None)
        link = self.work(leader=leader, name="Visible project")
        item = self.get(PROJECTS)["results"][0]
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
            item["project"], {"id": link.project_id, "name": "Visible project"}
        )
        self.assertEqual(
            item["leader"],
            {"user_id": leader.pk, "full_name": "Анна Иванова", "avatar": None},
        )
        self.assertEqual(parse_datetime(item["submitted_at"]), NOW - timedelta(hours=1))

    def test_serializer_only_defensively_accepts_null_leader_without_schema_change(self):
        # Project.leader is NOT NULL today; exercise the nullable response contract only.
        link = SimpleNamespace(
            pk=1,
            project=SimpleNamespace(id=2, name="Legacy project", leader=None),
            datetime_submitted=None,
            status="awaiting_evaluation",
            assignments_total=0,
            assignments_completed=0,
        )
        with self.assertNumQueries(0):
            data = ProgramAttentionProjectSerializer(link).data
        self.assertIsNone(data["leader"])
        self.assertIsNone(data["submitted_at"])

    def test_sort_is_oldest_submission_then_link_id_and_unknown_dates_last(self):
        newest = self.work(hours=1)
        older = self.work(hours=2)
        tied = self.work(hours=2)
        unknown = self.work(hours=3)
        PartnerProgramProject.objects.filter(pk=unknown.pk).update(
            datetime_submitted=None
        )
        expected = [older.pk, tied.pk, newest.pk, unknown.pk]
        for _ in range(2):
            self.assertEqual(
                [item["program_project_id"] for item in self.get(PROJECTS)["results"]],
                expected,
            )

    def test_search_is_trimmed_case_insensitive_and_name_only(self):
        link = self.work(name="Unique Project")
        self.work(name="Other", description="Unique Project")
        for search in (" UNIQUE ", "project"):
            with self.subTest(search=search):
                data = self.get(PROJECTS, search=search)
                self.assertEqual(data["count"], 1)
                self.assertEqual(data["results"][0]["program_project_id"], link.pk)

    def test_search_finds_work_outside_default_first_page(self):
        for index in range(25):
            self.work(name=f"Old project {index}", hours=2)
        target = self.work(name="SearchTarget", hours=1)
        page = self.get(PROJECTS)
        self.assertEqual(page["count"], 26)
        self.assertEqual(len(page["results"]), 25)
        self.assertNotIn(
            target.pk, [item["program_project_id"] for item in page["results"]]
        )
        data = self.get(PROJECTS, search="SearchTarget")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["program_project_id"], target.pk)

    def test_project_pagination_preserves_mode_and_search(self):
        links = [self.work(name=f"Needle {index}") for index in range(3)]
        first = self.get(PROJECTS, limit=2, search="Needle")
        self.assertEqual(first["mode"], "distributed")
        self.assertEqual(first["count"], 3)
        self.assertEqual(
            parse_qs(urlparse(first["next"]).query),
            {"limit": ["2"], "search": ["Needle"], "offset": ["2"]},
        )
        second = self.get(PROJECTS, limit=2, offset=2, search="Needle")
        self.assertEqual(second["results"][0]["program_project_id"], links[-1].pk)
        self.assertIsNotNone(second["previous"])
        self.assertIsNone(second["next"])

    def test_distributed_count_matches_overview_for_all_completion_states(self):
        self.work()
        self.assignment(self.work())
        partial = self.work()
        self.assignment(partial)
        self.assignment(partial, expert=create_rate_expert(program=self.program))
        self.score(partial)
        completed = self.work()
        self.assignment(completed)
        self.score(completed)
        self.assignment(self.work(submitted=False))
        self.assertEqual(self.get(PROJECTS)["count"], 3)
        self.assert_matches_overview(PROJECTS, "projects_awaiting_evaluation")

    def test_open_count_matches_overview_without_using_distributed_rules(self):
        self.open_mode()
        self.work()
        evaluated = self.work()
        self.score(evaluated, criteria=self.criteria[:1])
        self.work(submitted=False)
        self.assertEqual(self.get(PROJECTS)["count"], 1)
        self.assert_matches_overview(PROJECTS, "projects_awaiting_evaluation")

    def test_query_count_is_constant_when_work_page_and_assignments_grow(self):
        self.assignment(self.work())
        with CaptureQueriesContext(connection) as small:
            self.get(PROJECTS, limit=100)
        for _ in range(30):
            self.assignment(self.work())
        with CaptureQueriesContext(connection) as large:
            data = self.get(PROJECTS, limit=100)
        self.assertEqual(len(data["results"]), 31)
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 4)
