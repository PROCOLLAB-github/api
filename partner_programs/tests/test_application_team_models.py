from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from partner_programs.models import Application, Team, TeamMember
from partner_programs.tests.helpers import create_partner_program, create_user


class ApplicationTeamModelTests(TestCase):
    def setUp(self):
        self.program = create_partner_program()
        self.captain = create_user(prefix="team-captain")

    def create_application(self, *, participation_mode=None, user=None):
        owner = user or self.captain
        data = {
            "program": self.program,
            "user": owner,
            "created_by": owner,
        }
        if participation_mode is not None:
            data["participation_mode"] = participation_mode
        return Application.objects.create(**data)

    def create_team(self, *, application=None, captain=None, name="Team"):
        return Team.objects.create(
            application=application
            or self.create_application(
                participation_mode=Application.PARTICIPATION_MODE_TEAM
            ),
            captain=captain or self.captain,
            name=name,
        )

    def test_participation_mode_defaults_to_individual(self):
        application = self.create_application()

        self.assertEqual(
            application.participation_mode,
            Application.PARTICIPATION_MODE_INDIVIDUAL,
        )

    def test_participation_mode_choices_contain_expected_values(self):
        self.assertEqual(
            {value for value, _label in Application.PARTICIPATION_MODE_CHOICES},
            {"undecided", "individual", "team"},
        )

    def test_existing_individual_application_flow_still_works(self):
        application = self.create_application()

        self.assertEqual(application.user, self.captain)
        self.assertEqual(application.created_by, self.captain)
        self.assertEqual(application.status, Application.STATUS_DRAFT)
        self.assertFalse(hasattr(application, "team"))

    def test_team_can_be_created_for_team_application(self):
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        )

        team = self.create_team(application=application)

        self.assertEqual(team.application, application)
        self.assertEqual(team.captain, self.captain)

    def test_team_cannot_be_created_for_individual_application(self):
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_INDIVIDUAL
        )

        with self.assertRaises(ValidationError) as error:
            self.create_team(application=application)

        self.assertIn("application", error.exception.message_dict)

    def test_team_cannot_be_created_for_undecided_application(self):
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_UNDECIDED
        )

        with self.assertRaises(ValidationError) as error:
            self.create_team(application=application)

        self.assertIn("application", error.exception.message_dict)

    def test_team_captain_must_match_application_user(self):
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        )
        another_user = create_user(prefix="another-captain")

        with self.assertRaises(ValidationError) as error:
            self.create_team(application=application, captain=another_user)

        self.assertIn("captain", error.exception.message_dict)

    def test_application_can_have_only_one_team(self):
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        )
        self.create_team(application=application)

        with self.assertRaises(ValidationError):
            self.create_team(application=application, name="Another team")

    def test_accepted_captain_member_can_be_created(self):
        team = self.create_team()

        member = TeamMember.objects.create(
            team=team,
            user=self.captain,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )

        self.assertEqual(member.user, team.captain)
        self.assertIsNone(member.invited_by)
        self.assertIsNotNone(member.joined_at)

    def test_captain_member_must_match_team_captain(self):
        team = self.create_team()
        another_user = create_user(prefix="captain-member")

        with self.assertRaises(ValidationError) as error:
            TeamMember.objects.create(
                team=team,
                user=another_user,
                role=TeamMember.ROLE_CAPTAIN,
                status=TeamMember.STATUS_ACCEPTED,
            )

        self.assertIn("user", error.exception.message_dict)

    def test_captain_member_must_be_accepted(self):
        team = self.create_team()

        for member_status in (
            TeamMember.STATUS_INVITED,
            TeamMember.STATUS_DECLINED,
            TeamMember.STATUS_REMOVED,
            TeamMember.STATUS_LEFT,
        ):
            with self.subTest(status=member_status):
                with self.assertRaises(ValidationError) as error:
                    TeamMember.objects.create(
                        team=team,
                        user=self.captain,
                        role=TeamMember.ROLE_CAPTAIN,
                        status=member_status,
                    )

                self.assertIn("status", error.exception.message_dict)

    def test_user_cannot_have_two_memberships_in_same_team(self):
        team = self.create_team()
        user = create_user(prefix="duplicate-member")
        TeamMember.objects.create(
            team=team,
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_INVITED,
        )

        with self.assertRaises(ValidationError):
            TeamMember.objects.create(
                team=team,
                user=user,
                role=TeamMember.ROLE_MEMBER,
                status=TeamMember.STATUS_ACCEPTED,
            )

    def test_regular_member_can_be_invited(self):
        team = self.create_team()
        user = create_user(prefix="invited-member")

        member = TeamMember.objects.create(
            team=team,
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_INVITED,
            invited_by=self.captain,
        )

        self.assertEqual(member.status, TeamMember.STATUS_INVITED)
        self.assertEqual(member.invited_by, self.captain)
        self.assertIsNone(member.joined_at)

    def test_regular_member_can_become_accepted(self):
        team = self.create_team()
        user = create_user(prefix="accepted-member")
        member = TeamMember.objects.create(
            team=team,
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_INVITED,
        )

        member.status = TeamMember.STATUS_ACCEPTED
        member.save()
        member.refresh_from_db()

        self.assertEqual(member.status, TeamMember.STATUS_ACCEPTED)
        self.assertIsNotNone(member.joined_at)

    def test_explicit_joined_at_is_preserved(self):
        team = self.create_team()
        joined_at = timezone.now() - timezone.timedelta(days=1)

        member = TeamMember.objects.create(
            team=team,
            user=create_user(prefix="joined-member"),
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            joined_at=joined_at,
        )

        self.assertEqual(member.joined_at, joined_at)

    def test_removed_or_left_member_keeps_joined_at(self):
        team = self.create_team()
        member = TeamMember.objects.create(
            team=team,
            user=create_user(prefix="former-member"),
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
        )
        joined_at = member.joined_at

        for member_status in (
            TeamMember.STATUS_REMOVED,
            TeamMember.STATUS_LEFT,
        ):
            member.status = member_status
            member.save()
            member.refresh_from_db()

            self.assertEqual(member.joined_at, joined_at)

    def test_deleting_team_deletes_members(self):
        team = self.create_team()
        member = TeamMember.objects.create(
            team=team,
            user=create_user(prefix="deleted-team-member"),
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_INVITED,
        )

        team.delete()

        self.assertFalse(TeamMember.objects.filter(pk=member.pk).exists())


class ApplicationTeamDatabaseConstraintTests(TransactionTestCase):
    def setUp(self):
        self.program = create_partner_program()
        self.captain = create_user(prefix="constraint-captain")
        self.application = Application.objects.create(
            program=self.program,
            user=self.captain,
            created_by=self.captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        )
        self.team = Team.objects.create(
            application=self.application,
            captain=self.captain,
            name="Constraint team",
        )

    def test_one_to_one_application_constraint_is_enforced_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Team.objects.bulk_create(
                [
                    Team(
                        application=self.application,
                        captain=self.captain,
                        name="Duplicate team",
                    )
                ]
            )

    def test_team_user_constraint_is_enforced_by_database(self):
        user = create_user(prefix="constraint-member")
        TeamMember.objects.create(
            team=self.team,
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_INVITED,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMember.objects.bulk_create(
                [
                    TeamMember(
                        team=self.team,
                        user=user,
                        role=TeamMember.ROLE_MEMBER,
                        status=TeamMember.STATUS_ACCEPTED,
                    )
                ]
            )

    def test_only_one_accepted_captain_constraint_is_enforced_by_database(self):
        TeamMember.objects.create(
            team=self.team,
            user=self.captain,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )
        another_user = create_user(prefix="second-constraint-captain")

        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMember.objects.bulk_create(
                [
                    TeamMember(
                        team=self.team,
                        user=another_user,
                        role=TeamMember.ROLE_CAPTAIN,
                        status=TeamMember.STATUS_ACCEPTED,
                    )
                ]
            )

    def test_captain_status_check_constraint_is_enforced_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMember.objects.bulk_create(
                [
                    TeamMember(
                        team=self.team,
                        user=self.captain,
                        role=TeamMember.ROLE_CAPTAIN,
                        status=TeamMember.STATUS_INVITED,
                    )
                ]
            )
