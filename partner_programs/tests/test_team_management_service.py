from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from partner_programs.models import Application, PartnerProgram, Team, TeamMember
from partner_programs.permissions import can_edit_application
from partner_programs.services.application_team import (
    ActiveApplicationConflictError,
    ApplicationDeadlinePassedError,
    ApplicationNotEditableError,
    TeamMemberRegistrationMissingError,
    create_or_get_application,
)
from partner_programs.services.team_management import (
    CaptainTransferRequiredError,
    CaptainTransferTargetInvalidError,
    TeamManagementPermissionError,
    TeamMemberNotFoundError,
    TeamMemberNotRemovableError,
    TeamMembershipNotActiveError,
    leave_team,
    remove_team_member,
    rename_team,
    transfer_team_captain,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_project,
    create_user,
)


class TeamManagementServiceTests(TestCase):
    def setUp(self):
        self.captain = create_user(prefix="team-service-captain")
        self.member_user = create_user(prefix="team-service-member")
        self.manager = create_user(prefix="team-service-manager")
        self.staff = create_user(prefix="team-service-staff", is_staff=True)
        self.outsider = create_user(prefix="team-service-outsider")
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
            team_name="Команда",
        ).application
        self.team = self.application.team
        self.member = TeamMember.objects.create(
            team=self.team,
            user=self.member_user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=self.captain,
        )

    def add_member(self, *, status=TeamMember.STATUS_ACCEPTED, register=True):
        user = create_user(prefix="team-service-extra")
        if register:
            create_program_member(self.program, user=user)
        return TeamMember.objects.create(
            team=self.team,
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=status,
            invited_by=self.captain,
        )

    def close_deadline(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=(
                timezone.now() - timezone.timedelta(seconds=1)
            )
        )

    def test_captain_and_staff_can_rename_draft_team(self):
        renamed = rename_team(team=self.team, actor=self.captain, name="Новое имя")
        self.assertEqual(renamed.name, "Новое имя")

        renamed = rename_team(team=renamed, actor=self.staff, name="Имя staff")
        self.assertEqual(renamed.name, "Имя staff")

    def test_member_manager_and_outsider_cannot_rename_team(self):
        for actor in (self.member_user, self.manager, self.outsider):
            with self.subTest(actor=actor):
                with self.assertRaises(TeamManagementPermissionError):
                    rename_team(team=self.team, actor=actor, name="Запрещено")

    def test_rename_is_blocked_after_deadline_or_submit(self):
        self.close_deadline()
        with self.assertRaises(ApplicationDeadlinePassedError):
            rename_team(team=self.team, actor=self.captain, name="Поздно")

        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=None
        )
        Application.objects.filter(pk=self.application.pk).update(
            status=Application.STATUS_SUBMITTED
        )
        with self.assertRaises(ApplicationNotEditableError):
            rename_team(team=self.team, actor=self.captain, name="Отправлено")

    def test_accepted_member_can_leave_and_joined_at_is_preserved(self):
        joined_at = self.member.joined_at
        left = leave_team(team=self.team, actor=self.member_user)

        self.assertEqual(left.status, TeamMember.STATUS_LEFT)
        self.assertEqual(left.joined_at, joined_at)

    def test_repeated_leave_returns_stable_domain_error(self):
        leave_team(team=self.team, actor=self.member_user)

        with self.assertRaises(TeamMembershipNotActiveError) as context:
            leave_team(team=self.team, actor=self.member_user)

        self.assertEqual(context.exception.code, "team_membership_not_active")

    def test_captain_must_transfer_before_leaving(self):
        with self.assertRaises(CaptainTransferRequiredError) as context:
            leave_team(team=self.team, actor=self.captain)
        self.assertEqual(context.exception.code, "captain_transfer_required")

    def test_leave_is_blocked_after_deadline_or_submit(self):
        self.close_deadline()
        with self.assertRaises(ApplicationDeadlinePassedError):
            leave_team(team=self.team, actor=self.member_user)

        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=None
        )
        Application.objects.filter(pk=self.application.pk).update(
            status=Application.STATUS_SUBMITTED
        )
        with self.assertRaises(ApplicationNotEditableError):
            leave_team(team=self.team, actor=self.member_user)

    def test_captain_removes_accepted_or_invited_member_without_deleting_history(self):
        joined_at = self.member.joined_at
        removed = remove_team_member(
            team=self.team,
            actor=self.captain,
            member_id=self.member.pk,
        )
        self.assertEqual(removed.status, TeamMember.STATUS_REMOVED)
        self.assertEqual(removed.joined_at, joined_at)

        invited = self.add_member(status=TeamMember.STATUS_INVITED, register=False)
        removed_invited = remove_team_member(
            team=self.team,
            actor=self.captain,
            member_id=invited.pk,
        )
        self.assertEqual(removed_invited.status, TeamMember.STATUS_REMOVED)
        self.assertTrue(TeamMember.objects.filter(pk=invited.pk).exists())

    def test_staff_can_remove_member_but_member_and_manager_cannot(self):
        removed = remove_team_member(
            team=self.team,
            actor=self.staff,
            member_id=self.member.pk,
        )
        self.assertEqual(removed.status, TeamMember.STATUS_REMOVED)

        for actor in (self.member_user, self.manager):
            other = self.add_member()
            with self.subTest(actor=actor):
                with self.assertRaises(TeamManagementPermissionError):
                    remove_team_member(
                        team=self.team,
                        actor=actor,
                        member_id=other.pk,
                    )

    def test_captain_cannot_remove_self(self):
        captain_member = self.team.members.get(role=TeamMember.ROLE_CAPTAIN)
        with self.assertRaises(CaptainTransferRequiredError):
            remove_team_member(
                team=self.team,
                actor=self.captain,
                member_id=captain_member.pk,
            )

    def test_remove_rejects_member_of_other_team_and_historical_status(self):
        other_captain = create_user(prefix="other-team-captain")
        create_program_member(self.program, user=other_captain)
        other_application = create_or_get_application(
            program=self.program,
            user=other_captain,
            created_by=other_captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        ).application
        other_member = other_application.team.members.get()

        with self.assertRaises(TeamMemberNotFoundError):
            remove_team_member(
                team=self.team,
                actor=self.captain,
                member_id=other_member.pk,
            )

        self.member.status = TeamMember.STATUS_LEFT
        self.member.save(update_fields=["status", "updated_at"])
        with self.assertRaises(TeamMemberNotRemovableError):
            remove_team_member(
                team=self.team,
                actor=self.captain,
                member_id=self.member.pk,
            )

    def test_remove_is_blocked_after_deadline_or_submit(self):
        self.close_deadline()
        with self.assertRaises(ApplicationDeadlinePassedError):
            remove_team_member(
                team=self.team,
                actor=self.captain,
                member_id=self.member.pk,
            )

        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=None
        )
        Application.objects.filter(pk=self.application.pk).update(
            status=Application.STATUS_SUBMITTED
        )
        with self.assertRaises(ApplicationNotEditableError):
            remove_team_member(
                team=self.team,
                actor=self.captain,
                member_id=self.member.pk,
            )

    def test_transfer_updates_owner_captain_roles_and_preserves_history(self):
        project = create_project(leader=self.captain)
        self.application.project = project
        self.application.save(update_fields=["project", "updated_at"])
        created_by_id = self.application.created_by_id

        transferred = transfer_team_captain(
            team=self.team,
            actor=self.captain,
            member_id=self.member.pk,
        )

        self.application.refresh_from_db()
        self.member.refresh_from_db()
        old_member = transferred.members.get(user=self.captain)
        self.assertEqual(transferred.captain, self.member_user)
        self.assertEqual(self.application.user, self.member_user)
        self.assertEqual(self.application.created_by_id, created_by_id)
        self.assertEqual(self.application.project, project)
        self.assertEqual(self.member.role, TeamMember.ROLE_CAPTAIN)
        self.assertEqual(self.member.status, TeamMember.STATUS_ACCEPTED)
        self.assertEqual(old_member.role, TeamMember.ROLE_MEMBER)
        self.assertEqual(old_member.status, TeamMember.STATUS_ACCEPTED)
        self.assertEqual(
            transferred.members.filter(
                role=TeamMember.ROLE_CAPTAIN,
                status=TeamMember.STATUS_ACCEPTED,
            ).count(),
            1,
        )
        self.assertTrue(can_edit_application(self.member_user, self.application))
        self.assertFalse(can_edit_application(self.captain, self.application))

    def test_staff_can_transfer_captain(self):
        transferred = transfer_team_captain(
            team=self.team,
            actor=self.staff,
            member_id=self.member.pk,
        )
        self.assertEqual(transferred.captain, self.member_user)

    def test_transfer_rejects_non_manager_actor(self):
        for actor in (self.member_user, self.manager, self.outsider):
            with self.subTest(actor=actor):
                with self.assertRaises(TeamManagementPermissionError):
                    transfer_team_captain(
                        team=self.team,
                        actor=actor,
                        member_id=self.member.pk,
                    )

    def test_transfer_rejects_non_accepted_or_non_member_target(self):
        for member_status in (
            TeamMember.STATUS_INVITED,
            TeamMember.STATUS_DECLINED,
            TeamMember.STATUS_REMOVED,
            TeamMember.STATUS_LEFT,
        ):
            self.member.status = member_status
            self.member.save(update_fields=["status", "updated_at"])
            with self.subTest(status=member_status):
                with self.assertRaises(CaptainTransferTargetInvalidError):
                    transfer_team_captain(
                        team=self.team,
                        actor=self.captain,
                        member_id=self.member.pk,
                    )

    def test_transfer_rejects_member_of_other_team(self):
        other_captain = create_user(prefix="transfer-other-captain")
        create_program_member(self.program, user=other_captain)
        other_application = create_or_get_application(
            program=self.program,
            user=other_captain,
            created_by=other_captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        ).application
        target = other_application.team.members.get()

        with self.assertRaises(TeamMemberNotFoundError):
            transfer_team_captain(
                team=self.team,
                actor=self.captain,
                member_id=target.pk,
            )

    def test_transfer_requires_program_registration(self):
        self.member_user.partner_program_profiles.filter(
            partner_program=self.program
        ).delete()

        with self.assertRaises(TeamMemberRegistrationMissingError):
            transfer_team_captain(
                team=self.team,
                actor=self.captain,
                member_id=self.member.pk,
            )

    def test_transfer_rejects_target_with_owned_active_application(self):
        Application.objects.create(
            program=self.program,
            user=self.member_user,
            created_by=self.member_user,
        )

        with self.assertRaises(ActiveApplicationConflictError):
            transfer_team_captain(
                team=self.team,
                actor=self.captain,
                member_id=self.member.pk,
            )

    def test_transfer_rejects_target_in_another_active_team(self):
        other_captain = create_user(prefix="conflict-team-captain")
        create_program_member(self.program, user=other_captain)
        other_application = create_or_get_application(
            program=self.program,
            user=other_captain,
            created_by=other_captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        ).application
        TeamMember.objects.create(
            team=other_application.team,
            user=self.member_user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=other_captain,
        )

        with self.assertRaises(ActiveApplicationConflictError):
            transfer_team_captain(
                team=self.team,
                actor=self.captain,
                member_id=self.member.pk,
            )

    def test_transfer_is_blocked_after_deadline_or_submit(self):
        self.close_deadline()
        with self.assertRaises(ApplicationDeadlinePassedError):
            transfer_team_captain(
                team=self.team,
                actor=self.captain,
                member_id=self.member.pk,
            )

        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=None
        )
        Application.objects.filter(pk=self.application.pk).update(
            status=Application.STATUS_SUBMITTED
        )
        with self.assertRaises(ApplicationNotEditableError):
            transfer_team_captain(
                team=self.team,
                actor=self.captain,
                member_id=self.member.pk,
            )

    def test_transfer_rolls_back_if_update_fails_midway(self):
        with patch.object(Team, "save", side_effect=RuntimeError("forced error")):
            with self.assertRaises(RuntimeError):
                transfer_team_captain(
                    team=self.team,
                    actor=self.captain,
                    member_id=self.member.pk,
                )

        self.application.refresh_from_db()
        self.team.refresh_from_db()
        self.member.refresh_from_db()
        old_captain = self.team.members.get(user=self.captain)
        self.assertEqual(self.application.user, self.captain)
        self.assertEqual(self.team.captain, self.captain)
        self.assertEqual(old_captain.role, TeamMember.ROLE_CAPTAIN)
        self.assertEqual(self.member.role, TeamMember.ROLE_MEMBER)
