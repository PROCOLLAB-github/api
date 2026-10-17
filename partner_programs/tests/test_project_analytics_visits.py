from datetime import datetime, timedelta, timezone as datetime_timezone

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_expert


NOW = datetime(2026, 9, 5, 12, tzinfo=datetime_timezone.utc)
PARTICIPANTS = "project-analytics-participants-without-team"
ONBOARDING = "project-analytics-participants-without-onboarding"
VISITS = "project-analytics-participants-without-visit"
PROJECTS = "project-analytics-projects-awaiting-evaluation"


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
            kwargs={"program_id": (program or self.program).pk},
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
            self.get("project-analytics")["attention"][metric],
        )


class ParticipantsWithoutVisitTests(AttentionAnalyticsTestCase):
    def test_new_endpoint_keeps_manager_permissions_and_program_scope(self):
        self.participant()
        self.participant(program=self.other_program)
        denied = [None, create_user(), self.expert]
        other_manager = create_user()
        self.other_program.managers.add(other_manager)
        denied.append(other_manager)
        for user in denied:
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                response = self.client.get(self.url(VISITS))
                self.assertEqual(response.status_code, 401 if user is None else 403)
        for user in (self.manager, create_user(is_staff=True), create_user(is_superuser=True)):
            self.client.force_authenticate(user)
            response = self.client.get(self.url(VISITS))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(self.url(VISITS), {}).status_code, 405)

    def test_only_both_missing_timestamps_are_included(self):
        missing = self.participant(onboarding_stage=None, is_active=True)
        also_missing = self.participant(onboarding_stage=0, is_active=False)
        self.participant(last_activity=NOW)
        self.participant(last_login=NOW)
        self.participant(last_activity=NOW, last_login=NOW)
        page = self.get(VISITS)
        self.assertEqual(page["count"], 2)
        self.assertEqual(
            {row["user_id"] for row in page["results"]},
            {missing.user_id, also_missing.user_id},
        )
        self.assert_matches_overview(VISITS, "participants_without_visit")

    def test_either_recorded_timestamp_removes_participant_from_attention(self):
        for field in ("last_activity", "last_login"):
            with self.subTest(field=field):
                registration = self.participant(onboarding_stage=0)
                self.assertEqual(self.get(VISITS)["count"], 1)
                setattr(registration.user, field, NOW)
                registration.user.save(update_fields=[field])
                self.assertEqual(self.get(VISITS)["count"], 0)
                overview = self.get("project-analytics")
                self.assertEqual(overview["attention"]["participants_without_visit"], 0)
                self.assertEqual(
                    overview["participant_funnel"]["visited_participants"],
                    overview["participant_funnel"]["unique_participants"],
                )

    def test_real_login_updates_both_funnel_and_attention_without_onboarding(self):
        registration = self.participant(onboarding_stage=0, is_active=True)
        self.assertEqual(self.get(VISITS)["count"], 1)
        login = APIClient().post(
            reverse("token_obtain_pair"),
            {"email": registration.user.email, "password": "pass"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        registration.user.refresh_from_db()
        self.assertIsNone(registration.user.last_activity)
        self.assertIsNotNone(registration.user.last_login)
        self.assertEqual(registration.user.onboarding_stage, 0)
        self.assertEqual(self.get(VISITS)["count"], 0)
        overview = self.get("project-analytics")
        self.assertEqual(overview["participant_funnel"]["visited_participants"], 1)
        self.assertEqual(overview["attention"]["participants_without_visit"], 0)

    def test_activity_before_program_registration_still_counts_as_a_visit(self):
        self.participant(last_activity=NOW - timedelta(days=100))
        self.participant(last_login=NOW - timedelta(days=100))
        self.assertEqual(self.get(VISITS)["count"], 0)
        self.assertEqual(
            self.get("project-analytics")["participant_funnel"]["visited_participants"],
            2,
        )

    def test_team_membership_does_not_invent_a_visit(self):
        registration = self.participant(onboarding_stage=None)
        self.work(leader=registration.user)
        self.assertEqual(self.get(VISITS)["count"], 1)
        self.assertEqual(self.get(PARTICIPANTS)["count"], 0)

    def test_other_program_unregistered_and_deleted_users_are_excluded(self):
        included = self.participant()
        self.participant(program=self.other_program)
        create_user()
        deleted = self.participant()
        deleted.user.delete()
        page = self.get(VISITS)
        self.assertEqual(page["count"], 1)
        self.assertEqual(page["results"][0]["user_id"], included.user_id)
        self.assert_matches_overview(VISITS, "participants_without_visit")

    def test_search_and_pagination_exclude_visited_users_before_counting(self):
        oldest = self.participant(hours=20, first_name="Alice")
        newest = self.participant(hours=1, first_name="Alice")
        self.participant(hours=30, first_name="Bob")
        self.participant(hours=40, first_name="Alice", last_activity=NOW)
        self.participant(hours=50, first_name="Alice", last_login=NOW)
        first = self.get(VISITS, search=" alice ", limit=1)
        second = self.get(VISITS, search="alice", limit=1, offset=1)
        self.assertEqual(first["count"], 2)
        self.assertEqual(first["results"][0]["user_id"], oldest.user_id)
        self.assertEqual(second["results"][0]["user_id"], newest.user_id)
        self.assertIsNotNone(first["next"])
        self.assertIsNone(second["next"])

    def test_list_returns_only_safe_public_participant_fields(self):
        self.participant(first_name="", last_name="")
        row = self.get(VISITS)["results"][0]
        self.assertEqual(
            set(row), {"user_id", "full_name", "avatar", "city", "registered_at"}
        )
