from django.test import TestCase

from partner_programs.models import Application, PartnerProgram, Submission, TeamMember
from partner_programs.permissions import (
    can_edit_application,
    can_edit_submission,
    can_manage_team,
    can_view_application,
    can_view_submission,
    can_view_team,
    is_accepted_team_member,
    is_application_owner,
    is_program_manager,
    is_team_captain,
)
from partner_programs.services.application_team import create_or_get_application
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)


class TeamPermissionHelperTests(TestCase):
    def setUp(self):
        self.captain = create_user(prefix="team-permission-captain")
        self.member_user = create_user(prefix="team-permission-member")
        self.manager = create_user(prefix="team-permission-manager")
        self.staff = create_user(prefix="team-permission-staff", is_staff=True)
        self.outsider = create_user(prefix="team-permission-outsider")
        self.program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=5,
        )
        self.program.managers.add(self.manager)
        create_program_member(self.program, user=self.captain)
        create_program_member(self.program, user=self.member_user)
        self.application = create_or_get_application(
            program=self.program,
            user=self.captain,
            created_by=self.captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        ).application
        self.member = TeamMember.objects.create(
            team=self.application.team,
            user=self.member_user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=self.captain,
        )
        self.submission = Submission.objects.create(
            application=self.application,
            program=self.program,
            submitted_by=self.captain,
            title="Решение",
        )

    def test_role_helpers_distinguish_owner_captain_member_and_manager(self):
        self.assertTrue(is_application_owner(self.captain, self.application))
        self.assertTrue(is_team_captain(self.captain, self.application.team))
        self.assertTrue(
            is_accepted_team_member(self.member_user, self.application.team)
        )
        self.assertTrue(is_program_manager(self.manager, self.program))
        self.assertFalse(is_application_owner(self.member_user, self.application))
        self.assertFalse(is_team_captain(self.member_user, self.application.team))

    def test_application_read_access_matches_role_boundary(self):
        for user in (self.captain, self.member_user, self.manager, self.staff):
            with self.subTest(user=user):
                self.assertTrue(can_view_application(user, self.application))
        self.assertFalse(can_view_application(self.outsider, self.application))

    def test_application_write_access_is_owner_or_staff_only(self):
        self.assertTrue(can_edit_application(self.captain, self.application))
        self.assertTrue(can_edit_application(self.staff, self.application))
        self.assertFalse(can_edit_application(self.member_user, self.application))
        self.assertFalse(can_edit_application(self.manager, self.application))

    def test_team_access_separates_view_and_manage(self):
        team = self.application.team
        for user in (self.captain, self.member_user, self.manager, self.staff):
            with self.subTest(user=user):
                self.assertTrue(can_view_team(user, team))
        self.assertTrue(can_manage_team(self.captain, team))
        self.assertTrue(can_manage_team(self.staff, team))
        self.assertFalse(can_manage_team(self.member_user, team))
        self.assertFalse(can_manage_team(self.manager, team))

    def test_historical_membership_does_not_grant_read_access(self):
        for membership_status in (
            TeamMember.STATUS_INVITED,
            TeamMember.STATUS_DECLINED,
            TeamMember.STATUS_REMOVED,
            TeamMember.STATUS_LEFT,
        ):
            self.member.status = membership_status
            self.member.save(update_fields=["status", "updated_at"])
            with self.subTest(status=membership_status):
                self.assertFalse(
                    is_accepted_team_member(self.member_user, self.application.team)
                )
                self.assertFalse(can_view_team(self.member_user, self.application.team))
                self.assertFalse(can_view_application(self.member_user, self.application))

    def test_submission_read_is_inherited_but_write_is_not(self):
        for user in (self.captain, self.member_user, self.manager, self.staff):
            with self.subTest(user=user):
                self.assertTrue(can_view_submission(user, self.submission))
        self.assertFalse(can_view_submission(self.outsider, self.submission))
        self.assertTrue(can_edit_submission(self.captain, self.submission))
        self.assertTrue(can_edit_submission(self.staff, self.submission))
        self.assertFalse(can_edit_submission(self.member_user, self.submission))
        self.assertFalse(can_edit_submission(self.manager, self.submission))
