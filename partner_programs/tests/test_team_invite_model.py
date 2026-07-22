from django.db import IntegrityError, transaction
from django.test import TestCase

from partner_programs.models import (
    Application,
    PartnerProgram,
    TeamInvite,
    TeamMember,
)
from partner_programs.services.application_team import create_or_get_application
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)


class TeamInviteModelTests(TestCase):
    def setUp(self):
        self.captain = create_user(prefix="invite-model-captain")
        self.target = create_user(prefix="invite-model-target")
        self.program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=5,
        )
        create_program_member(self.program, user=self.captain)
        create_program_member(self.program, user=self.target)
        self.application = create_or_get_application(
            program=self.program,
            user=self.captain,
            created_by=self.captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="Модельная команда",
        ).application
        self.team = self.application.team

    def create_invite(self, **overrides):
        defaults = {
            "team": self.team,
            "user": self.target,
            "invited_by": self.captain,
        }
        defaults.update(overrides)
        return TeamInvite.objects.create(**defaults)

    def test_statuses_and_default(self):
        invite = self.create_invite()

        self.assertEqual(invite.status, TeamInvite.STATUS_PENDING)
        self.assertEqual(
            {value for value, _label in TeamInvite.STATUS_CHOICES},
            {"pending", "accepted", "declined", "revoked"},
        )

    def test_only_one_pending_invite_per_team_and_user(self):
        self.create_invite()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_invite()

    def test_resolved_invite_allows_new_pending_invite(self):
        resolved = self.create_invite(status=TeamInvite.STATUS_DECLINED)
        pending = self.create_invite()

        self.assertNotEqual(resolved.pk, pending.pk)
        self.assertEqual(
            TeamInvite.objects.filter(team=self.team, user=self.target).count(),
            2,
        )

    def test_timestamps_are_filled(self):
        invite = self.create_invite()

        self.assertIsNotNone(invite.created_at)
        self.assertIsNotNone(invite.updated_at)
        self.assertIsNone(invite.resolved_at)

    def test_creating_invite_does_not_create_team_member(self):
        self.create_invite()

        self.assertFalse(
            TeamMember.objects.filter(team=self.team, user=self.target).exists()
        )
