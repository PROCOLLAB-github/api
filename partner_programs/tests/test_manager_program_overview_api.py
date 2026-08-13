# Roadmap: DEV-076, DEV-056, DEV-091

import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    Evaluation,
    PartnerProgramUserProfile,
    Submission,
    SubmissionExpertAssignment,
    Team,
    TeamMember,
)
from partner_programs.tests.helpers import create_partner_program, create_user
from project_rates.tests.helpers import create_rate_expert


class ManagerProgramOverviewAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = create_user(prefix="overview-manager")
        self.other_manager = create_user(prefix="overview-other-manager")
        self.participant = create_user(prefix="overview-participant")
        self.staff = create_user(prefix="overview-staff", is_staff=True)
        self.superuser = create_user(
            prefix="overview-superuser",
            is_staff=True,
            is_superuser=True,
        )
        self.program = create_partner_program(name="Overview program")
        self.other_program = create_partner_program(name="Other program")
        self.program.managers.add(self.manager)
        self.other_program.managers.add(self.other_manager)
        self.url = reverse(
            "partner_programs:manager-overview",
            kwargs={"program_id": self.program.pk},
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_application(
        self,
        *,
        program=None,
        status=Application.STATUS_DRAFT,
        participation_mode=Application.PARTICIPATION_MODE_INDIVIDUAL,
        prefix="overview-application",
    ):
        program = program or self.program
        user = create_user(prefix=prefix)
        return Application.objects.create(
            program=program,
            user=user,
            created_by=user,
            status=status,
            participation_mode=participation_mode,
            form_data={
                "email": f"{prefix}@private.example",
                "private_answer": "hidden application data",
            },
        )

    def create_submission(self, application, status_value, version):
        return Submission.objects.create(
            application=application,
            program=application.program,
            submitted_by=application.user,
            title=f"Private solution {version}",
            description="Hidden solution contents",
            form_data={"private_solution": True},
            links=["https://private.example/file"],
            status=status_value,
            version=version,
        )

    def seed_complete_overview(self, program, manager, prefix):
        for index in range(2):
            PartnerProgramUserProfile.objects.create(
                user=create_user(prefix=f"{prefix}-registration-{index}"),
                partner_program=program,
                partner_program_data={"private_registration": index},
            )

        application_specs = (
            (
                Application.STATUS_DRAFT,
                Application.PARTICIPATION_MODE_UNDECIDED,
            ),
            (
                Application.STATUS_SUBMITTED,
                Application.PARTICIPATION_MODE_INDIVIDUAL,
            ),
            (
                Application.STATUS_APPROVED,
                Application.PARTICIPATION_MODE_TEAM,
            ),
            (
                Application.STATUS_REJECTED,
                Application.PARTICIPATION_MODE_UNDECIDED,
            ),
            (
                Application.STATUS_WITHDRAWN,
                Application.PARTICIPATION_MODE_INDIVIDUAL,
            ),
            (
                Application.STATUS_CANCELLED,
                Application.PARTICIPATION_MODE_TEAM,
            ),
        )
        applications = {}
        for index, (status_value, participation_mode) in enumerate(
            application_specs,
            start=1,
        ):
            applications[status_value] = self.create_application(
                program=program,
                status=status_value,
                participation_mode=participation_mode,
                prefix=f"{prefix}-application-{index}",
            )

        team_application = applications[Application.STATUS_APPROVED]
        team = Team.objects.create(
            application=team_application,
            captain=team_application.user,
            name="Private team name",
        )
        TeamMember.objects.create(
            team=team,
            user=team_application.user,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )
        for member_status in (
            TeamMember.STATUS_ACCEPTED,
            TeamMember.STATUS_INVITED,
            TeamMember.STATUS_DECLINED,
            TeamMember.STATUS_REMOVED,
            TeamMember.STATUS_LEFT,
        ):
            TeamMember.objects.create(
                team=team,
                user=create_user(prefix=f"{prefix}-member-{member_status}"),
                status=member_status,
            )

        submission_application = applications[Application.STATUS_SUBMITTED]
        submissions = {}
        for version, status_value in enumerate(
            (
                Submission.STATUS_DRAFT,
                Submission.STATUS_SUBMITTED,
                Submission.STATUS_RETURNED,
                Submission.STATUS_FINAL,
                Submission.STATUS_CANCELLED,
            ),
            start=1,
        ):
            submissions[status_value] = self.create_submission(
                submission_application,
                status_value,
                version,
            )

        expert_user = create_rate_expert(prefix=f"{prefix}-expert", program=program)
        expert = expert_user.expert
        SubmissionExpertAssignment.objects.create(
            submission=submissions[Submission.STATUS_SUBMITTED],
            expert=expert,
            assigned_by=manager,
            status=SubmissionExpertAssignment.STATUS_ASSIGNED,
        )
        SubmissionExpertAssignment.objects.create(
            submission=submissions[Submission.STATUS_FINAL],
            expert=expert,
            assigned_by=manager,
            status=SubmissionExpertAssignment.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        SubmissionExpertAssignment.objects.create(
            submission=submissions[Submission.STATUS_RETURNED],
            expert=expert,
            assigned_by=manager,
            status=SubmissionExpertAssignment.STATUS_REVOKED,
            revoked_by=manager,
            revoked_at=timezone.now(),
            revoke_reason="Private reason",
        )

        Evaluation.objects.create(
            submission=submissions[Submission.STATUS_SUBMITTED],
            expert=expert,
            status=Evaluation.STATUS_DRAFT,
            comment="Private draft comment",
        )
        Evaluation.objects.create(
            submission=submissions[Submission.STATUS_FINAL],
            expert=expert,
            status=Evaluation.STATUS_SUBMITTED,
            comment="Private submitted comment",
            submitted_at=timezone.now(),
        )

    def get_as(self, user):
        self.authenticate(user)
        return self.client.get(self.url)

    def test_program_manager_gets_overview(self):
        response = self.get_as(self.manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["program"]["id"], self.program.pk)

    def test_staff_gets_overview(self):
        response = self.get_as(self.staff)

        self.assertEqual(response.status_code, 200)

    def test_superuser_gets_overview(self):
        response = self.get_as(self.superuser)

        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_user_gets_401(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_participant_gets_403(self):
        response = self.get_as(self.participant)

        self.assertEqual(response.status_code, 403)

    def test_manager_of_another_program_gets_403(self):
        response = self.get_as(self.other_manager)

        self.assertEqual(response.status_code, 403)

    def test_unknown_program_gets_404(self):
        self.authenticate(self.manager)

        response = self.client.get(
            reverse(
                "partner_programs:manager-overview",
                kwargs={"program_id": self.program.pk + self.other_program.pk + 1000},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_empty_program_returns_full_zero_contract(self):
        response = self.get_as(self.manager)

        self.assertEqual(
            response.data,
            {
                "program": {"id": self.program.pk, "name": "Overview program"},
                "registrations": {"total": 0},
                "participants": {"total": 0},
                "applications": {
                    "total": 0,
                    "by_status": {
                        "draft": 0,
                        "submitted": 0,
                        "approved": 0,
                        "rejected": 0,
                        "withdrawn": 0,
                        "cancelled": 0,
                    },
                    "by_participation_mode": {
                        "undecided": 0,
                        "individual": 0,
                        "team": 0,
                    },
                },
                "teams": {"total": 0, "accepted_members": 0},
                "submissions": {
                    "total": 0,
                    "by_status": {
                        "draft": 0,
                        "submitted": 0,
                        "returned": 0,
                        "final": 0,
                        "cancelled": 0,
                    },
                    "applications_with_submitted_solution": 0,
                },
                "expert_assignments": {
                    "total": 0,
                    "by_status": {
                        "assigned": 0,
                        "completed": 0,
                        "revoked": 0,
                    },
                },
                "evaluations": {
                    "total": 0,
                    "by_status": {"draft": 0, "submitted": 0},
                },
            },
        )

    def test_all_domain_counters_follow_the_contract(self):
        self.seed_complete_overview(self.program, self.manager, "overview-own")

        response = self.get_as(self.manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["registrations"], {"total": 2})
        self.assertEqual(response.data["participants"], {"total": 2})
        self.assertEqual(response.data["applications"]["total"], 6)
        self.assertEqual(
            response.data["applications"]["by_status"],
            {
                "draft": 1,
                "submitted": 1,
                "approved": 1,
                "rejected": 1,
                "withdrawn": 1,
                "cancelled": 1,
            },
        )
        self.assertEqual(
            response.data["applications"]["by_participation_mode"],
            {"undecided": 2, "individual": 2, "team": 2},
        )
        self.assertEqual(
            response.data["teams"],
            {"total": 1, "accepted_members": 2},
        )
        self.assertEqual(response.data["submissions"]["total"], 5)
        self.assertEqual(
            response.data["submissions"]["by_status"],
            {
                "draft": 1,
                "submitted": 1,
                "returned": 1,
                "final": 1,
                "cancelled": 1,
            },
        )
        self.assertEqual(
            response.data["submissions"]["applications_with_submitted_solution"],
            1,
        )
        self.assertEqual(
            response.data["expert_assignments"],
            {
                "total": 3,
                "by_status": {"assigned": 1, "completed": 1, "revoked": 1},
            },
        )
        self.assertEqual(
            response.data["evaluations"],
            {"total": 2, "by_status": {"draft": 1, "submitted": 1}},
        )

    def test_other_program_data_does_not_change_counters(self):
        self.seed_complete_overview(self.program, self.manager, "overview-own")
        self.seed_complete_overview(
            self.other_program,
            self.other_manager,
            "overview-other",
        )

        response = self.get_as(self.manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["program"]["id"], self.program.pk)
        self.assertEqual(response.data["registrations"]["total"], 2)
        self.assertEqual(response.data["participants"]["total"], 2)
        self.assertEqual(response.data["applications"]["total"], 6)
        self.assertEqual(response.data["teams"]["total"], 1)
        self.assertEqual(response.data["submissions"]["total"], 5)
        self.assertEqual(response.data["expert_assignments"]["total"], 3)
        self.assertEqual(response.data["evaluations"]["total"], 2)

    def test_participants_count_only_non_null_unique_users(self):
        for index in range(2):
            PartnerProgramUserProfile.objects.create(
                user=create_user(prefix=f"overview-unique-participant-{index}"),
                partner_program=self.program,
                partner_program_data={"registration": index},
            )
        for index in range(2):
            PartnerProgramUserProfile.objects.create(
                user=None,
                partner_program=self.program,
                partner_program_data={"deleted_user_registration": index},
            )

        response = self.get_as(self.manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["registrations"], {"total": 4})
        self.assertEqual(response.data["participants"], {"total": 2})

    def test_response_does_not_contain_pii_or_private_content(self):
        self.seed_complete_overview(self.program, self.manager, "overview-private")

        response = self.get_as(self.manager)

        self.assertEqual(response.status_code, 200)
        serialized = json.dumps(response.data, ensure_ascii=False)
        for private_value in (
            "private.example",
            "hidden application data",
            "Private solution",
            "Hidden solution contents",
            "Private team name",
            "Private reason",
            "Private draft comment",
            "Private submitted comment",
        ):
            self.assertNotIn(private_value, serialized)

        forbidden_keys = {
            "email",
            "first_name",
            "last_name",
            "form_data",
            "partner_program_data",
            "links",
            "description",
            "comment",
            "scores",
        }

        def assert_safe_keys(value):
            if isinstance(value, dict):
                self.assertTrue(forbidden_keys.isdisjoint(value.keys()))
                for nested_value in value.values():
                    assert_safe_keys(nested_value)
            elif isinstance(value, list):
                for nested_value in value:
                    assert_safe_keys(nested_value)

        assert_safe_keys(response.data)

    def test_manager_query_count_has_constant_upper_bound(self):
        self.seed_complete_overview(self.program, self.manager, "overview-query")
        self.authenticate(self.manager)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 8)

    def test_staff_query_count_has_constant_upper_bound_and_same_contract(self):
        self.seed_complete_overview(self.program, self.manager, "overview-staff-query")
        manager_response = self.get_as(self.manager)
        self.authenticate(self.staff)

        with CaptureQueriesContext(connection) as queries:
            staff_response = self.client.get(self.url)

        self.assertEqual(staff_response.status_code, 200)
        self.assertLessEqual(len(queries), 7)
        self.assertEqual(staff_response.data, manager_response.data)
