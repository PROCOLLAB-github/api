"""Program-scoped legacy leader DTO, separate from the production Application domain."""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from courses.models import CourseAccessType
from invites.models import Invite
from partner_programs.models import (
    Application,
    PartnerProgram,
    PartnerProgramMaterial,
    PartnerProgramProject,
    Team,
    TeamMember,
)
from partner_programs.selectors import get_current_project_application
from partner_programs.serializers import (
    PartnerProgramForMemberSerializer,
    PartnerProgramForUnregisteredUserSerializer,
)
from partner_programs.tests.helpers import (
    create_course,
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from partner_programs.views import PartnerProgramDetail
from projects.models import Collaborator


class ProgramCurrentProjectApplicationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = create_user()
        self.program = create_partner_program()
        self.project = create_project(leader=self.user, draft=True)
        self.client.force_authenticate(self.user)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def get_detail(self, program=None):
        program = program or self.program
        response = self.client.get(f"/programs/{program.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("current_project_application", response.data)
        self.assertNotIn("current_application", response.data)
        return response

    def assert_current_project(self, response, link):
        self.assertEqual(
            response.json()["current_project_application"],
            {
                "project_id": link.project_id,
                "program_link_id": link.pk,
                "submitted": link.submitted,
            },
        )

    def test_anonymous_user_skips_lookup_and_receives_null(self):
        create_program_member(self.program, user=self.user)
        create_program_project(self.program, project=self.project)
        self.client.force_authenticate(None)
        with patch("partner_programs.views.get_current_project_application") as lookup:
            response = self.get_detail()
        lookup.assert_not_called()
        self.assertFalse(response.data["is_user_member"])
        self.assertIsNone(response.data["current_project_application"])

    def test_non_member_with_owned_link_and_membership_elsewhere_skips_lookup(self):
        create_program_project(self.program, project=self.project)
        create_program_member(create_partner_program(), user=self.user)
        with patch("partner_programs.views.get_current_project_application") as lookup:
            response = self.get_detail()
        lookup.assert_not_called()
        self.assertFalse(response.data["is_user_member"])
        self.assertIsNone(response.data["current_project_application"])

    def test_manager_without_membership_receives_null(self):
        self.program.managers.add(self.user)
        create_program_project(self.program, project=self.project)
        with patch("partner_programs.views.get_current_project_application") as lookup:
            response = self.get_detail()
        lookup.assert_not_called()
        self.assertTrue(response.data["is_user_manager"])
        self.assertIsNone(response.data["current_project_application"])

    def test_member_without_legacy_link_receives_null(self):
        create_program_member(self.program, user=self.user)
        response = self.get_detail()
        self.assertTrue(response.data["is_user_member"])
        self.assertIsNone(response.data["current_project_application"])

    def test_member_receives_draft_link_without_production_application(self):
        create_program_member(self.program, user=self.user)
        link = create_program_project(self.program, project=self.project)
        self.assertFalse(Application.objects.exists())
        self.assert_current_project(self.get_detail(), link)

    def test_submitted_is_raw_link_state_even_for_draft_noncompetitive_project(self):
        create_program_member(self.program, user=self.user)
        link = create_program_project(self.program, project=self.project, submitted=True)
        self.assertFalse(self.program.is_competitive)
        self.assertTrue(self.project.draft)
        self.assert_current_project(self.get_detail(), link)

    def test_shared_project_returns_requested_program_link_not_first_link(self):
        create_program_project(self.program, project=self.project, submitted=True)
        program_b = create_partner_program()
        create_program_member(program_b, user=self.user)
        link_b = create_program_project(program_b, project=self.project)
        self.assert_current_project(self.get_detail(program_b), link_b)

    def test_separate_projects_return_only_requested_program_application(self):
        create_program_project(self.program, project=self.project)
        program_b = create_partner_program()
        create_program_member(program_b, user=self.user)
        link_b = create_program_project(
            program_b, project=create_project(leader=self.user)
        )
        self.assert_current_project(self.get_detail(program_b), link_b)

    def test_other_leaders_project_is_not_current_project_application(self):
        create_program_member(self.program, user=self.user)
        create_program_project(self.program)
        self.assertIsNone(self.get_detail().data["current_project_application"])

    def test_collaborator_in_another_leaders_project_receives_null(self):
        create_program_member(self.program, user=self.user)
        link = create_program_project(self.program)
        Collaborator.objects.create(user=self.user, project=link.project)
        self.assertIsNone(self.get_detail().data["current_project_application"])

    def test_invited_user_in_another_leaders_project_receives_null(self):
        create_program_member(self.program, user=self.user)
        link = create_program_project(self.program)
        Invite.objects.create(user=self.user, project=link.project)
        self.assertIsNone(self.get_detail().data["current_project_application"])

    def test_team_membership_does_not_grant_legacy_application_ownership(self):
        self.program.participation_format = (
            PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM
        )
        self.program.team_min_size = 2
        self.program.team_max_size = 5
        self.program.save()
        create_program_member(self.program, user=self.user)
        other_leader = create_user()
        create_program_member(self.program, user=other_leader)
        foreign_project = create_project(leader=other_leader)
        create_program_project(self.program, project=foreign_project)
        application = Application.objects.create(
            program=self.program,
            user=other_leader,
            created_by=other_leader,
            project=foreign_project,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        )
        team = Team.objects.create(application=application, captain=other_leader)
        TeamMember.objects.create(
            team=team,
            user=other_leader,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )
        TeamMember.objects.create(
            team=team, user=self.user, status=TeamMember.STATUS_ACCEPTED
        )
        self.assertIsNone(self.get_detail().data["current_project_application"])

    def test_duplicate_fallback_is_minimum_link_pk_not_minimum_project_pk(self):
        create_program_member(self.program, user=self.user)
        later_project = create_project(leader=self.user)
        first_link = create_program_project(
            self.program, project=later_project, submitted=True
        )
        create_program_project(self.program, project=self.project)
        self.assertLess(self.project.pk, later_project.pk)
        self.assert_current_project(self.get_detail(), first_link)

    def test_profile_project_without_legacy_link_is_not_an_application(self):
        create_program_member(self.program, user=self.user, project=self.project)
        self.assertIsNone(self.get_detail().data["current_project_application"])

    def test_stale_profile_project_does_not_override_authoritative_link(self):
        create_program_member(
            self.program, user=self.user, project=create_project(leader=self.user)
        )
        link = create_program_project(self.program, project=self.project)
        self.assert_current_project(self.get_detail(), link)

    def test_real_application_only_does_not_create_legacy_dto(self):
        create_program_member(self.program, user=self.user)
        Application.objects.create(
            program=self.program,
            user=self.user,
            created_by=self.user,
            project=self.project,
        )
        self.assertFalse(PartnerProgramProject.objects.exists())
        self.assertIsNone(self.get_detail().data["current_project_application"])

    def test_real_application_and_legacy_link_return_only_legacy_data(self):
        create_program_member(self.program, user=self.user)
        application = Application.objects.create(
            program=self.program,
            user=self.user,
            created_by=self.user,
            project=create_project(leader=self.user),
            status=Application.STATUS_DRAFT,
        )
        link = create_program_project(self.program, project=self.project, submitted=True)
        applications_before = list(Application.objects.values())
        self.assertNotEqual(application.project_id, link.project_id)
        self.assert_current_project(self.get_detail(), link)
        self.assertEqual(list(Application.objects.values()), applications_before)

    def test_application_in_another_program_does_not_affect_result(self):
        create_program_member(self.program, user=self.user)
        other_program = create_partner_program()
        create_program_member(other_program, user=self.user)
        Application.objects.create(
            program=other_program,
            user=self.user,
            created_by=self.user,
            project=self.project,
        )
        self.assertIsNone(self.get_detail().data["current_project_application"])
        link = create_program_project(self.program, project=self.project)
        self.assert_current_project(self.get_detail(), link)

    def test_existing_production_detail_contract_is_preserved(self):
        profile = create_program_member(self.program, user=self.user)
        profile.welcome_acknowledged_at = timezone.now()
        profile.save(update_fields=["welcome_acknowledged_at"])
        self.program.managers.add(self.user)
        create_program_project(self.program, project=self.project)
        course = create_course(self.program, access_type=CourseAccessType.PROGRAM_MEMBERS)
        material = PartnerProgramMaterial.objects.create(
            program=self.program, title="Guide", url="https://example.com/guide.pdf"
        )
        for user, is_member in ((None, False), (create_user(), False), (self.user, True)):
            with self.subTest(member=is_member, user=getattr(user, "pk", None)):
                self.client.force_authenticate(user)
                response = self.get_detail()
                request = response.renderer_context["request"]
                serializer_class = (
                    PartnerProgramForMemberSerializer
                    if is_member
                    else PartnerProgramForUnregisteredUserSerializer
                )
                expected = serializer_class(
                    PartnerProgramDetail.queryset.get(pk=self.program.pk),
                    context={
                        "request": request,
                        "user": request.user,
                        "program_user_profile": profile if is_member else None,
                    },
                ).data
                self.assertEqual(
                    {
                        key: value
                        for key, value in response.data.items()
                        if key != "current_project_application"
                    },
                    {**expected, "is_user_member": is_member},
                )
                self.assertIs(
                    "application_policy" in response.data,
                    settings.NEXTGEN_SURFACE_ENABLED,
                )
                self.assertIs(response.data["is_user_manager"], is_member)
                self.assertEqual(
                    response.data["materials"],
                    [{"title": material.title, "url": material.url}],
                )
                self.assertEqual(
                    response.data["courses"],
                    [{"id": course.pk, "title": course.title, "is_available": is_member}],
                )
                if is_member:
                    self.assertIsNotNone(response.data["welcome_acknowledged_at"])
        profile.refresh_from_db()
        self.assertIsNotNone(profile.welcome_acknowledged_at)

    def test_member_adds_exactly_one_lookup_to_existing_detail_queries(self):
        create_program_member(self.program, user=self.user)
        link = create_program_project(self.program, project=self.project)
        self.get_detail()  # Warm existing counters/content types and add_view once.
        with patch(
            "partner_programs.views.get_current_project_application", return_value=None
        ), CaptureQueriesContext(connection) as without_lookup:
            self.get_detail()
        with patch(
            "partner_programs.views.get_current_project_application",
            wraps=get_current_project_application,
        ) as lookup, CaptureQueriesContext(connection) as with_lookup:
            response = self.get_detail()
        lookup.assert_called_once_with(program_id=self.program.pk, user_id=self.user.pk)
        self.assertEqual(len(with_lookup), len(without_lookup) + 1)
        self.assert_current_project(response, link)

    def test_selector_is_one_query_for_empty_one_or_many_matching_projects(self):
        with self.assertNumQueries(1):
            result = get_current_project_application(
                program_id=self.program.pk, user_id=self.user.pk
            )
        self.assertIsNone(result)
        link = create_program_project(self.program, project=self.project)
        for extra_projects in (0, 19):
            for _ in range(extra_projects):
                create_program_project(
                    self.program, project=create_project(leader=self.user)
                )
            with self.subTest(extra_projects=extra_projects), self.assertNumQueries(1):
                result = get_current_project_application(
                    program_id=self.program.pk, user_id=self.user.pk
                )
            self.assertEqual(
                result,
                {
                    "project_id": self.project.pk,
                    "program_link_id": link.pk,
                    "submitted": False,
                },
            )
