from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from partner_programs.models import Application, PartnerProgram
from partner_programs.serializers.programs import (
    PartnerProgramForMemberSerializer,
    PartnerProgramForUnregisteredUserSerializer,
    PartnerProgramListSerializer,
)
from partner_programs.tests.helpers import create_partner_program


class PartnerProgramParticipationPolicyTests(TestCase):
    def assert_policy_invalid(self, expected_field, **overrides):
        program = create_partner_program(data_schema={"field": "value"})
        for field, value in overrides.items():
            setattr(program, field, value)

        with self.assertRaises(ValidationError) as error:
            program.full_clean()

        self.assertIn(expected_field, error.exception.message_dict)

    def test_participation_format_defaults_to_individual_only(self):
        program = create_partner_program()

        self.assertEqual(
            program.participation_format,
            PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_ONLY,
        )

    def test_team_min_size_defaults_to_null(self):
        program = create_partner_program()

        self.assertIsNone(program.team_min_size)

    def test_team_max_size_defaults_to_null(self):
        program = create_partner_program()

        self.assertIsNone(program.team_max_size)

    def test_application_deadline_defaults_to_null(self):
        program = create_partner_program()

        self.assertIsNone(program.datetime_application_ends)

    def test_participation_format_choices_contain_expected_values(self):
        self.assertEqual(
            {value for value, _label in PartnerProgram.PARTICIPATION_FORMAT_CHOICES},
            {"individual_only", "team_only", "individual_or_team"},
        )

    def test_individual_only_without_team_sizes_is_valid(self):
        program = create_partner_program(data_schema={"field": "value"})

        program.full_clean()

    def test_individual_only_with_team_min_size_is_invalid(self):
        self.assert_policy_invalid("team_min_size", team_min_size=2)

    def test_individual_only_with_team_max_size_is_invalid(self):
        self.assert_policy_invalid("team_max_size", team_max_size=5)

    def test_team_only_without_team_sizes_is_invalid(self):
        self.assert_policy_invalid(
            "team_min_size",
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
        )

    def test_individual_or_team_without_team_sizes_is_invalid(self):
        self.assert_policy_invalid(
            "team_max_size",
            participation_format=(PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM),
        )

    def test_team_min_size_less_than_two_is_invalid(self):
        self.assert_policy_invalid(
            "team_min_size",
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=1,
            team_max_size=5,
        )

    def test_team_max_size_less_than_minimum_is_invalid(self):
        self.assert_policy_invalid(
            "team_max_size",
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=5,
            team_max_size=4,
        )

    def test_team_only_with_valid_sizes_is_valid(self):
        program = create_partner_program(data_schema={"field": "value"})
        program.participation_format = PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY
        program.team_min_size = 2
        program.team_max_size = 5

        program.full_clean()

    def test_individual_or_team_with_valid_sizes_is_valid(self):
        program = create_partner_program(data_schema={"field": "value"})
        program.participation_format = (
            PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM
        )
        program.team_min_size = 2
        program.team_max_size = 5

        program.full_clean()

    def test_individual_only_allows_individual_mode(self):
        program = create_partner_program()

        self.assertTrue(
            program.allows_participation_mode(Application.PARTICIPATION_MODE_INDIVIDUAL)
        )

    def test_individual_only_rejects_team_mode(self):
        program = create_partner_program()

        self.assertFalse(
            program.allows_participation_mode(Application.PARTICIPATION_MODE_TEAM)
        )

    def test_team_only_allows_team_mode(self):
        program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=5,
        )

        self.assertTrue(
            program.allows_participation_mode(Application.PARTICIPATION_MODE_TEAM)
        )

    def test_team_only_rejects_individual_mode(self):
        program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=5,
        )

        self.assertFalse(
            program.allows_participation_mode(Application.PARTICIPATION_MODE_INDIVIDUAL)
        )

    def test_individual_or_team_allows_both_final_modes(self):
        program = create_partner_program(
            participation_format=(PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM),
            team_min_size=2,
            team_max_size=5,
        )

        self.assertTrue(
            program.allows_participation_mode(Application.PARTICIPATION_MODE_INDIVIDUAL)
        )
        self.assertTrue(
            program.allows_participation_mode(Application.PARTICIPATION_MODE_TEAM)
        )

    def test_undecided_is_not_an_allowed_final_mode(self):
        program = create_partner_program(
            participation_format=(PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM),
            team_min_size=2,
            team_max_size=5,
        )

        self.assertFalse(
            program.allows_participation_mode(Application.PARTICIPATION_MODE_UNDECIDED)
        )

    def test_unknown_participation_mode_is_not_allowed(self):
        program = create_partner_program()

        self.assertFalse(program.allows_participation_mode("unknown"))

    def test_null_application_deadline_is_not_passed(self):
        program = create_partner_program(datetime_application_ends=None)

        self.assertFalse(program.is_application_deadline_passed())

    def test_future_application_deadline_is_not_passed(self):
        program = create_partner_program(
            datetime_application_ends=timezone.now() + timezone.timedelta(days=1)
        )

        self.assertFalse(program.is_application_deadline_passed())

    def test_past_application_deadline_is_passed(self):
        program = create_partner_program(
            datetime_application_ends=timezone.now() - timezone.timedelta(days=1)
        )

        self.assertTrue(program.is_application_deadline_passed())

    def test_application_deadline_accepts_explicit_moment(self):
        deadline = timezone.now()
        program = create_partner_program(datetime_application_ends=deadline)

        self.assertFalse(
            program.is_application_deadline_passed(
                at=deadline - timezone.timedelta(seconds=1)
            )
        )
        self.assertTrue(
            program.is_application_deadline_passed(
                at=deadline + timezone.timedelta(seconds=1)
            )
        )

    def test_public_program_serializers_do_not_expose_policy_fields(self):
        policy_fields = {
            "participation_format",
            "team_min_size",
            "team_max_size",
            "datetime_application_ends",
        }

        for serializer_class in (
            PartnerProgramListSerializer,
            PartnerProgramForMemberSerializer,
            PartnerProgramForUnregisteredUserSerializer,
        ):
            with self.subTest(serializer=serializer_class.__name__):
                self.assertTrue(
                    policy_fields.isdisjoint(serializer_class().fields.keys())
                )


class PartnerProgramParticipationPolicyConstraintTests(TransactionTestCase):
    def test_database_rejects_team_min_size_less_than_two(self):
        program = create_partner_program()

        with self.assertRaises(IntegrityError), transaction.atomic():
            PartnerProgram.objects.filter(pk=program.pk).update(
                participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
                team_min_size=1,
                team_max_size=5,
            )

    def test_database_rejects_team_max_size_less_than_minimum(self):
        program = create_partner_program()

        with self.assertRaises(IntegrityError), transaction.atomic():
            PartnerProgram.objects.filter(pk=program.pk).update(
                participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
                team_min_size=5,
                team_max_size=4,
            )

    def test_database_rejects_team_format_without_sizes(self):
        program = create_partner_program()

        with self.assertRaises(IntegrityError), transaction.atomic():
            PartnerProgram.objects.filter(pk=program.pk).update(
                participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
                team_min_size=None,
                team_max_size=None,
            )

    def test_database_rejects_individual_format_with_team_sizes(self):
        program = create_partner_program()

        with self.assertRaises(IntegrityError), transaction.atomic():
            PartnerProgram.objects.filter(pk=program.pk).update(
                participation_format=(
                    PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL_ONLY
                ),
                team_min_size=2,
                team_max_size=5,
            )
