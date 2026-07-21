from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from partner_programs.models import Application, PartnerProgram, Team, TeamMember
from partner_programs.services.application_team import (
    ActiveApplicationConflictError,
    ApplicationDeadlinePassedError,
    ApplicationNotEditableError,
    CaptainMemberMissingError,
    CaptainMismatchError,
    ParticipationModeNotAllowedError,
    ParticipationModeUndecidedError,
    RegistrationRequiredError,
    TeamHasOtherMembersError,
    TeamMemberRegistrationMissingError,
    TeamNotAllowedError,
    TeamRequiredError,
    TeamSizeInvalidError,
    change_application_participation_mode,
    create_or_get_application,
    submit_application,
    validate_team_invariants,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)


class ApplicationTeamServiceTests(TestCase):
    def setUp(self):
        self.program = create_partner_program()
        self.user = create_user(prefix="team-service-owner")
        self.registration = create_program_member(self.program, user=self.user)

    def configure_team_policy(
        self,
        *,
        participation_format=PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM,
        minimum=2,
        maximum=5,
    ):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            participation_format=participation_format,
            team_min_size=minimum,
            team_max_size=maximum,
        )
        self.program.refresh_from_db()

    def create_application(
        self,
        *,
        participation_mode=Application.PARTICIPATION_MODE_INDIVIDUAL,
        user=None,
        program=None,
        form_data=None,
        team_name=None,
    ):
        owner = user or self.user
        target_program = program or self.program
        return create_or_get_application(
            program=target_program,
            user=owner,
            created_by=owner,
            participation_mode=participation_mode,
            form_data=form_data,
            team_name=team_name,
        )

    def add_team_member(
        self,
        application,
        *,
        user=None,
        status=TeamMember.STATUS_ACCEPTED,
        register=True,
    ):
        member_user = user or create_user(prefix="team-service-member")
        if register:
            create_program_member(application.program, user=member_user)
        member = TeamMember.objects.create(
            team=application.team,
            user=member_user,
            role=TeamMember.ROLE_MEMBER,
            status=status,
            invited_by=application.user,
        )
        return member

    def test_registered_user_creates_individual_draft_without_team(self):
        result = self.create_application(form_data={"motivation": "test"})

        self.assertTrue(result.created)
        self.assertEqual(result.application.status, Application.STATUS_DRAFT)
        self.assertEqual(
            result.application.participation_mode,
            Application.PARTICIPATION_MODE_INDIVIDUAL,
        )
        self.assertFalse(Team.objects.filter(application=result.application).exists())

    def test_create_requires_registration(self):
        self.registration.delete()

        with self.assertRaises(RegistrationRequiredError):
            self.create_application()

        self.assertFalse(Application.objects.exists())

    def test_create_is_blocked_after_application_deadline(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=timezone.now() - timezone.timedelta(seconds=1)
        )

        with self.assertRaises(ApplicationDeadlinePassedError):
            self.create_application()

    def test_individual_is_forbidden_in_team_only_program(self):
        self.configure_team_policy(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY
        )

        with self.assertRaises(ParticipationModeNotAllowedError):
            self.create_application()

    def test_repeated_compatible_create_returns_existing_application(self):
        first = self.create_application(form_data={"version": 1})
        second = self.create_application(form_data={"version": 1})

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.application.pk, second.application.pk)
        self.assertEqual(Application.objects.count(), 1)

    def test_repeated_incompatible_create_is_rejected(self):
        self.create_application(form_data={"version": 1})

        with self.assertRaises(ActiveApplicationConflictError):
            self.create_application(form_data={"version": 2})

    def test_undecided_draft_can_be_created_without_team(self):
        result = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_UNDECIDED
        )

        self.assertEqual(
            result.application.participation_mode,
            Application.PARTICIPATION_MODE_UNDECIDED,
        )
        self.assertFalse(Team.objects.filter(application=result.application).exists())

    def test_undecided_application_cannot_be_submitted(self):
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_UNDECIDED
        ).application

        with self.assertRaises(ParticipationModeUndecidedError):
            submit_application(application=application, actor=self.user)

    def test_team_can_be_created_in_team_only_program(self):
        self.configure_team_policy(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY
        )

        result = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="Команда",
        )

        self.assertTrue(result.created)
        self.assertEqual(result.application.team.name, "Команда")

    def test_team_can_be_created_in_individual_or_team_program(self):
        self.configure_team_policy()

        result = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        )

        self.assertTrue(Team.objects.filter(application=result.application).exists())

    def test_team_is_forbidden_in_individual_only_program(self):
        with self.assertRaises(ParticipationModeNotAllowedError):
            self.create_application(
                participation_mode=Application.PARTICIPATION_MODE_TEAM
            )

    def test_team_create_atomically_creates_matching_accepted_captain(self):
        self.configure_team_policy()

        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        captain_member = application.team.members.get(role=TeamMember.ROLE_CAPTAIN)

        self.assertEqual(application.team.captain, application.user)
        self.assertEqual(captain_member.user, application.user)
        self.assertEqual(captain_member.status, TeamMember.STATUS_ACCEPTED)
        self.assertIsNone(captain_member.invited_by)
        self.assertIsNotNone(captain_member.joined_at)

    def test_team_create_rolls_back_application_after_internal_error(self):
        self.configure_team_policy()

        with patch(
            "partner_programs.services.application_team._create_team_with_captain",
            side_effect=RuntimeError("forced error"),
        ):
            with self.assertRaises(RuntimeError):
                self.create_application(
                    participation_mode=Application.PARTICIPATION_MODE_TEAM
                )

        self.assertFalse(Application.objects.exists())
        self.assertFalse(Team.objects.exists())
        self.assertFalse(TeamMember.objects.exists())

    def test_owner_cannot_create_incompatible_second_active_application(self):
        self.configure_team_policy()
        self.create_application()

        with self.assertRaises(ActiveApplicationConflictError):
            self.create_application(
                participation_mode=Application.PARTICIPATION_MODE_TEAM
            )

    def test_accepted_member_of_another_application_has_conflict(self):
        self.configure_team_policy()
        captain = create_user(prefix="other-team-captain")
        create_program_member(self.program, user=captain)
        other_application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            user=captain,
        ).application
        self.add_team_member(other_application, user=self.user, register=False)

        with self.assertRaises(ActiveApplicationConflictError):
            self.create_application()

    def test_terminal_application_does_not_block_new_application(self):
        first = self.create_application().application
        first.status = Application.STATUS_WITHDRAWN
        first.withdrawn_at = timezone.now()
        first.save(update_fields=["status", "withdrawn_at", "updated_at"])

        second = self.create_application()

        self.assertTrue(second.created)
        self.assertNotEqual(first.pk, second.application.pk)

    def test_membership_in_another_program_does_not_block_create(self):
        other_program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=5,
        )
        captain = create_user(prefix="other-program-captain")
        create_program_member(other_program, user=captain)
        create_program_member(other_program, user=self.user)
        other_application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            user=captain,
            program=other_program,
        ).application
        self.add_team_member(
            other_application,
            user=self.user,
            register=False,
        )

        result = self.create_application()

        self.assertTrue(result.created)

    def test_individual_to_team_creates_team_and_captain(self):
        self.configure_team_policy()
        application = self.create_application().application

        updated = change_application_participation_mode(
            application=application,
            actor=self.user,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="Новая команда",
        )

        self.assertEqual(
            updated.participation_mode,
            Application.PARTICIPATION_MODE_TEAM,
        )
        self.assertEqual(updated.team.name, "Новая команда")
        self.assertTrue(
            updated.team.members.filter(
                user=self.user,
                role=TeamMember.ROLE_CAPTAIN,
                status=TeamMember.STATUS_ACCEPTED,
            ).exists()
        )

    def test_team_to_individual_deletes_captain_only_team(self):
        self.configure_team_policy()
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        team_id = application.team.pk

        updated = change_application_participation_mode(
            application=application,
            actor=self.user,
            participation_mode=Application.PARTICIPATION_MODE_INDIVIDUAL,
        )

        self.assertEqual(
            updated.participation_mode,
            Application.PARTICIPATION_MODE_INDIVIDUAL,
        )
        self.assertFalse(Team.objects.filter(pk=team_id).exists())
        self.assertFalse(TeamMember.objects.filter(team_id=team_id).exists())

    def test_team_name_can_change_for_draft_before_deadline(self):
        self.configure_team_policy()
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="Старое название",
        ).application

        change_application_participation_mode(
            application=application,
            actor=self.user,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="Новое название",
        )

        application.team.refresh_from_db()
        self.assertEqual(application.team.name, "Новое название")

    def test_only_owner_can_change_participation_mode(self):
        application = self.create_application().application
        another_user = create_user(prefix="mode-change-actor")

        with self.assertRaises(ApplicationNotEditableError):
            change_application_participation_mode(
                application=application,
                actor=another_user,
                participation_mode=Application.PARTICIPATION_MODE_UNDECIDED,
            )

    def test_team_to_individual_is_forbidden_with_another_member_record(self):
        self.configure_team_policy()
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        self.add_team_member(
            application,
            status=TeamMember.STATUS_INVITED,
            register=False,
        )

        with self.assertRaises(TeamHasOtherMembersError):
            change_application_participation_mode(
                application=application,
                actor=self.user,
                participation_mode=Application.PARTICIPATION_MODE_INDIVIDUAL,
            )

        application.refresh_from_db()
        self.assertEqual(
            application.participation_mode,
            Application.PARTICIPATION_MODE_TEAM,
        )

    def test_team_to_undecided_is_forbidden(self):
        self.configure_team_policy()
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application

        with self.assertRaises(TeamNotAllowedError):
            change_application_participation_mode(
                application=application,
                actor=self.user,
                participation_mode=Application.PARTICIPATION_MODE_UNDECIDED,
            )

    def test_individual_to_undecided_is_allowed_for_draft(self):
        application = self.create_application().application

        updated = change_application_participation_mode(
            application=application,
            actor=self.user,
            participation_mode=Application.PARTICIPATION_MODE_UNDECIDED,
        )

        self.assertEqual(
            updated.participation_mode,
            Application.PARTICIPATION_MODE_UNDECIDED,
        )

    def test_participation_mode_cannot_change_after_submit(self):
        application = self.create_application().application
        submit_application(application=application, actor=self.user)

        with self.assertRaises(ApplicationNotEditableError):
            change_application_participation_mode(
                application=application,
                actor=self.user,
                participation_mode=Application.PARTICIPATION_MODE_UNDECIDED,
            )

    def test_participation_mode_cannot_change_after_deadline(self):
        application = self.create_application().application
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=timezone.now() - timezone.timedelta(seconds=1)
        )

        with self.assertRaises(ApplicationDeadlinePassedError):
            change_application_participation_mode(
                application=application,
                actor=self.user,
                participation_mode=Application.PARTICIPATION_MODE_UNDECIDED,
            )

    def test_participation_mode_must_match_program_policy(self):
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_UNDECIDED
        ).application

        with self.assertRaises(ParticipationModeNotAllowedError):
            change_application_participation_mode(
                application=application,
                actor=self.user,
                participation_mode=Application.PARTICIPATION_MODE_TEAM,
            )

    def test_team_invariant_requires_team(self):
        self.configure_team_policy()
        application = Application.objects.create(
            program=self.program,
            user=self.user,
            created_by=self.user,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        )

        with self.assertRaises(TeamRequiredError):
            validate_team_invariants(application)

    def test_team_invariant_requires_captain_member(self):
        self.configure_team_policy()
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        application.team.members.all().delete()

        with self.assertRaises(CaptainMemberMissingError):
            validate_team_invariants(application)

    def test_team_invariant_rejects_captain_mismatch(self):
        self.configure_team_policy()
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        another_user = create_user(prefix="mismatched-captain")
        Team.objects.filter(pk=application.team.pk).update(captain=another_user)

        with self.assertRaises(CaptainMismatchError):
            validate_team_invariants(application)

    def test_team_invariant_requires_registration_for_accepted_member(self):
        self.configure_team_policy()
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        self.add_team_member(application, register=False)

        with self.assertRaises(TeamMemberRegistrationMissingError):
            validate_team_invariants(application)

    def test_team_invariant_rejects_team_smaller_than_minimum(self):
        self.configure_team_policy(minimum=2, maximum=5)
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application

        with self.assertRaises(TeamSizeInvalidError):
            validate_team_invariants(application)

    def test_team_invariant_rejects_team_larger_than_maximum(self):
        self.configure_team_policy(minimum=2, maximum=2)
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        self.add_team_member(application)
        self.add_team_member(application)

        with self.assertRaises(TeamSizeInvalidError):
            validate_team_invariants(application)

    def test_valid_accepted_team_passes_invariant(self):
        self.configure_team_policy(minimum=2, maximum=3)
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        self.add_team_member(application)

        validate_team_invariants(application)

    def test_invited_member_is_not_counted_in_team_size(self):
        self.configure_team_policy(minimum=2, maximum=2)
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        self.add_team_member(application)
        self.add_team_member(
            application,
            status=TeamMember.STATUS_INVITED,
            register=False,
        )

        validate_team_invariants(application)

    def test_inactive_member_statuses_are_not_counted_in_team_size(self):
        self.configure_team_policy(minimum=2, maximum=2)
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        self.add_team_member(application)
        for member_status in (
            TeamMember.STATUS_DECLINED,
            TeamMember.STATUS_REMOVED,
            TeamMember.STATUS_LEFT,
        ):
            self.add_team_member(
                application,
                status=member_status,
                register=False,
            )

        validate_team_invariants(application)

    def test_individual_submit_transitions_application(self):
        application = self.create_application().application

        submitted = submit_application(application=application, actor=self.user)

        self.assertEqual(submitted.status, Application.STATUS_SUBMITTED)
        self.assertIsNotNone(submitted.submitted_at)

    def test_team_submit_with_valid_team_transitions_application(self):
        self.configure_team_policy(minimum=2, maximum=3)
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        self.add_team_member(application)

        submitted = submit_application(application=application, actor=self.user)

        self.assertEqual(submitted.status, Application.STATUS_SUBMITTED)

    def test_repeated_submit_is_idempotent(self):
        application = self.create_application().application
        first = submit_application(application=application, actor=self.user)

        second = submit_application(application=first, actor=self.user)

        self.assertEqual(second.status, Application.STATUS_SUBMITTED)
        self.assertEqual(second.pk, first.pk)

    def test_repeated_submit_preserves_submitted_at(self):
        application = self.create_application().application
        first = submit_application(application=application, actor=self.user)
        submitted_at = first.submitted_at

        second = submit_application(application=first, actor=self.user)

        self.assertEqual(second.submitted_at, submitted_at)

    def test_draft_submit_is_blocked_after_deadline(self):
        application = self.create_application().application
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=timezone.now() - timezone.timedelta(seconds=1)
        )

        with self.assertRaises(ApplicationDeadlinePassedError):
            submit_application(application=application, actor=self.user)

    def test_submitted_application_is_idempotent_after_deadline(self):
        application = self.create_application().application
        submitted = submit_application(application=application, actor=self.user)
        submitted_at = submitted.submitted_at
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=timezone.now() - timezone.timedelta(seconds=1)
        )

        repeated = submit_application(application=submitted, actor=self.user)

        self.assertEqual(repeated.submitted_at, submitted_at)

    def test_member_conflict_blocks_team_submit(self):
        self.configure_team_policy(minimum=2, maximum=3)
        application = self.create_application(
            participation_mode=Application.PARTICIPATION_MODE_TEAM
        ).application
        member = self.add_team_member(application)
        Application.objects.create(
            program=self.program,
            user=member.user,
            created_by=member.user,
        )

        with self.assertRaises(ActiveApplicationConflictError):
            submit_application(application=application, actor=self.user)

    def test_submit_requires_owner_registration(self):
        self.registration.delete()
        application = Application.objects.create(
            program=self.program,
            user=self.user,
            created_by=self.user,
        )

        with self.assertRaises(RegistrationRequiredError):
            submit_application(application=application, actor=self.user)


class ApplicationTeamServiceSequentialConflictTests(TransactionTestCase):
    def test_sequential_operations_do_not_create_second_active_participation(self):
        program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM,
            team_min_size=2,
            team_max_size=5,
        )
        captain = create_user(prefix="sequential-captain")
        member = create_user(prefix="sequential-member")
        create_program_member(program, user=captain)
        create_program_member(program, user=member)
        application = create_or_get_application(
            program=program,
            user=captain,
            created_by=captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        ).application
        TeamMember.objects.create(
            team=application.team,
            user=member,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=captain,
        )

        with self.assertRaises(ActiveApplicationConflictError):
            create_or_get_application(
                program=program,
                user=member,
                created_by=member,
                participation_mode=Application.PARTICIPATION_MODE_INDIVIDUAL,
            )

        self.assertEqual(Application.objects.count(), 1)
