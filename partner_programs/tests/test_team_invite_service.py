from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from partner_programs.models import (
    Application,
    PartnerProgram,
    TeamInvite,
    TeamMember,
)
from partner_programs.services.application_team import (
    ApplicationDeadlinePassedError,
    ApplicationNotEditableError,
    TeamHasOtherMembersError,
    change_application_participation_mode,
    create_or_get_application,
    submit_application,
)
from partner_programs.services.team_invites import (
    TeamInviteActiveApplicationConflictError,
    TeamInviteCapacityReachedError,
    TeamInviteNotOwnedError,
    TeamInviteNotPendingError,
    TeamInvitePermissionError,
    TeamInviteRegistrationMissingError,
    TeamInviteTargetInvalidError,
    accept_team_invite,
    create_team_invite,
    decline_team_invite,
    revoke_team_invite,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)


class TeamInviteServiceTests(TestCase):
    def setUp(self):
        self.captain = create_user(prefix="invite-service-captain")
        self.target = create_user(prefix="invite-service-target")
        self.outsider = create_user(prefix="invite-service-outsider")
        self.program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=4,
        )
        create_program_member(self.program, user=self.captain)
        create_program_member(self.program, user=self.target)
        self.application = self.create_team_application(self.captain, "Команда один")
        self.team = self.application.team

    def create_team_application(self, captain, name):
        if not self.program.partner_program_profiles.filter(user=captain).exists():
            create_program_member(self.program, user=captain)
        return create_or_get_application(
            program=self.program,
            user=captain,
            created_by=captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name=name,
        ).application

    def create_pending_invite(self, *, team=None, target=None, actor=None):
        return create_team_invite(
            team=team or self.team,
            actor=actor or self.captain,
            target=target or self.target,
        ).invite

    def test_create_is_successful_idempotent_and_does_not_create_member(self):
        first = create_team_invite(
            team=self.team,
            actor=self.captain,
            target=self.target,
        )
        second = create_team_invite(
            team=self.team,
            actor=self.captain,
            target=self.target,
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.invite.pk, second.invite.pk)
        self.assertFalse(
            TeamMember.objects.filter(team=self.team, user=self.target).exists()
        )

    def test_only_captain_or_staff_can_create_and_revoke(self):
        with self.assertRaises(TeamInvitePermissionError):
            create_team_invite(
                team=self.team,
                actor=self.outsider,
                target=self.target,
            )

        staff = create_user(prefix="invite-service-staff", is_staff=True)
        invite = create_team_invite(
            team=self.team,
            actor=staff,
            target=self.target,
        ).invite
        revoked = revoke_team_invite(invite=invite, actor=staff)
        self.assertEqual(revoked.status, TeamInvite.STATUS_REVOKED)

    def test_target_must_not_be_captain_or_accepted_member(self):
        with self.assertRaises(TeamInviteTargetInvalidError):
            create_team_invite(
                team=self.team,
                actor=self.captain,
                target=self.captain,
            )

        TeamMember.objects.create(
            team=self.team,
            user=self.target,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=self.captain,
        )
        with self.assertRaises(TeamInviteTargetInvalidError):
            create_team_invite(
                team=self.team,
                actor=self.captain,
                target=self.target,
            )

    def test_registration_is_required(self):
        unregistered = create_user(prefix="invite-unregistered")

        with self.assertRaises(TeamInviteRegistrationMissingError):
            create_team_invite(
                team=self.team,
                actor=self.captain,
                target=unregistered,
            )

    def test_active_own_application_is_a_conflict(self):
        Application.objects.create(
            program=self.program,
            user=self.target,
            created_by=self.target,
        )

        with self.assertRaises(TeamInviteActiveApplicationConflictError):
            self.create_pending_invite()

    def test_accepted_membership_in_other_team_is_a_conflict(self):
        other_captain = create_user(prefix="invite-other-captain")
        other_application = self.create_team_application(other_captain, "Другая команда")
        TeamMember.objects.create(
            team=other_application.team,
            user=self.target,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=other_captain,
        )

        with self.assertRaises(TeamInviteActiveApplicationConflictError):
            self.create_pending_invite()

    def test_pending_invites_reserve_capacity(self):
        self.program.team_max_size = 2
        self.program.save(update_fields=["team_max_size"])
        self.create_pending_invite()
        second_target = create_user(prefix="invite-capacity-target")
        create_program_member(self.program, user=second_target)

        with self.assertRaises(TeamInviteCapacityReachedError):
            self.create_pending_invite(target=second_target)

    def test_deadline_and_non_draft_application_block_mutations(self):
        self.program.datetime_application_ends = (
            timezone.now() - timezone.timedelta(seconds=1)
        )
        self.program.save(update_fields=["datetime_application_ends"])
        with self.assertRaises(ApplicationDeadlinePassedError):
            self.create_pending_invite()

        self.program.datetime_application_ends = None
        self.program.save(update_fields=["datetime_application_ends"])
        self.application.status = Application.STATUS_SUBMITTED
        self.application.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ApplicationNotEditableError):
            self.create_pending_invite()

    def test_pending_invite_blocks_switch_to_individual(self):
        self.program.participation_format = (
            PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM
        )
        self.program.save(update_fields=["participation_format"])
        self.create_pending_invite()

        with self.assertRaises(TeamHasOtherMembersError):
            change_application_participation_mode(
                application=self.application,
                actor=self.captain,
                participation_mode=Application.PARTICIPATION_MODE_INDIVIDUAL,
            )

    def test_pending_invite_is_not_counted_as_member_on_submit(self):
        accepted_user = create_user(prefix="invite-submit-member")
        create_program_member(self.program, user=accepted_user)
        TeamMember.objects.create(
            team=self.team,
            user=accepted_user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=self.captain,
        )
        invite = self.create_pending_invite()

        submitted = submit_application(
            application=self.application,
            actor=self.captain,
        )

        invite.refresh_from_db()
        self.assertEqual(submitted.status, Application.STATUS_SUBMITTED)
        self.assertEqual(invite.status, TeamInvite.STATUS_PENDING)

    def test_accept_creates_member_and_is_idempotent(self):
        invite = self.create_pending_invite()

        accepted = accept_team_invite(invite=invite, actor=self.target)
        repeated = accept_team_invite(invite=accepted, actor=self.target)

        self.assertEqual(repeated.status, TeamInvite.STATUS_ACCEPTED)
        self.assertIsNotNone(repeated.resolved_at)
        members = TeamMember.objects.filter(team=self.team, user=self.target)
        self.assertEqual(members.count(), 1)
        self.assertEqual(members.get().status, TeamMember.STATUS_ACCEPTED)

    def test_accept_restores_historical_member_and_preserves_joined_at(self):
        joined_at = timezone.now() - timezone.timedelta(days=10)
        member = TeamMember.objects.create(
            team=self.team,
            user=self.target,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_LEFT,
            invited_by=self.captain,
            joined_at=joined_at,
        )
        invite = self.create_pending_invite()

        accept_team_invite(invite=invite, actor=self.target)

        member.refresh_from_db()
        self.assertEqual(member.status, TeamMember.STATUS_ACCEPTED)
        self.assertEqual(member.role, TeamMember.ROLE_MEMBER)
        self.assertEqual(member.joined_at, joined_at)
        self.assertEqual(
            TeamMember.objects.filter(team=self.team, user=self.target).count(),
            1,
        )

    def test_only_invitee_can_accept_or_decline(self):
        invite = self.create_pending_invite()

        with self.assertRaises(TeamInviteNotOwnedError):
            accept_team_invite(invite=invite, actor=self.outsider)
        with self.assertRaises(TeamInviteNotOwnedError):
            decline_team_invite(invite=invite, actor=self.outsider)

    def test_decline_and_revoke_are_idempotent(self):
        declined = decline_team_invite(
            invite=self.create_pending_invite(),
            actor=self.target,
        )
        repeated_decline = decline_team_invite(
            invite=declined,
            actor=self.target,
        )
        self.assertEqual(repeated_decline.status, TeamInvite.STATUS_DECLINED)
        self.assertIsNotNone(repeated_decline.resolved_at)

        second_target = create_user(prefix="invite-revoke-target")
        create_program_member(self.program, user=second_target)
        revoked = revoke_team_invite(
            invite=self.create_pending_invite(target=second_target),
            actor=self.captain,
        )
        repeated_revoke = revoke_team_invite(
            invite=revoked,
            actor=self.captain,
        )
        self.assertEqual(repeated_revoke.status, TeamInvite.STATUS_REVOKED)

    def test_other_terminal_transitions_return_stable_error(self):
        declined = decline_team_invite(
            invite=self.create_pending_invite(),
            actor=self.target,
        )

        with self.assertRaises(TeamInviteNotPendingError):
            accept_team_invite(invite=declined, actor=self.target)
        with self.assertRaises(TeamInviteNotPendingError):
            revoke_team_invite(invite=declined, actor=self.captain)

    def test_accept_revokes_other_pending_invites_in_same_program(self):
        first = self.create_pending_invite()
        other_captain = create_user(prefix="invite-second-captain")
        other_application = self.create_team_application(other_captain, "Команда два")
        second = self.create_pending_invite(
            team=other_application.team,
            target=self.target,
            actor=other_captain,
        )

        accept_team_invite(invite=first, actor=self.target)

        second.refresh_from_db()
        self.assertEqual(second.status, TeamInvite.STATUS_REVOKED)
        self.assertIsNotNone(second.resolved_at)

    def test_accept_rolls_back_membership_if_invite_update_fails(self):
        invite = self.create_pending_invite()

        with patch.object(TeamInvite, "save", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                accept_team_invite(invite=invite, actor=self.target)

        invite.refresh_from_db()
        self.assertEqual(invite.status, TeamInvite.STATUS_PENDING)
        self.assertFalse(
            TeamMember.objects.filter(team=self.team, user=self.target).exists()
        )
