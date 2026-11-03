from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from partner_programs.certificate_models import ProgramCertificateAsset
from partner_programs.models import PartnerProgram, PartnerProgramProject
from partner_programs.solution_api import create_solution
from partner_programs.solution_models import ProgramSolution
from partner_programs.tests.helpers import (
    create_partner_program,
    create_project,
    create_user,
)
from project_rates.tests.helpers import create_rate_expert
from scripts.prepare_pr517_closeout import prepare


class PR517CloseoutFixtureTests(TestCase):
    def setUp(self):
        self.manager = create_rate_expert()
        self.expert = create_rate_expert()
        self.captains = [
            create_user(is_active=True),
            self.expert,
            create_user(is_active=True),
        ]
        self.participant = create_user(is_active=True)
        self.previous_project = create_project(name="Существующий проект")
        self.previous_program = create_partner_program()
        ProgramCertificateAsset.objects.create(
            program=self.previous_program,
            kind="signature",
            name="existing.png",
            content=b"existing-private-binary",
            width=1,
            height=1,
        )
        self.args = (
            "test-fixture-20261103",
            self.manager.pk,
            [user.pk for user in self.captains],
            [self.manager.pk, self.expert.pk],
            self.participant.pk,
        )

    def test_preview_is_readonly_and_requires_existing_accounts(self):
        counts = (get_user_model().objects.count(), PartnerProgram.objects.count())
        result = prepare(*self.args)
        self.assertFalse(result["applied"])
        self.assertEqual(result["solution_count"], 21)
        self.assertEqual(
            (get_user_model().objects.count(), PartnerProgram.objects.count()), counts
        )
        with self.assertRaises(ValueError):
            prepare(self.args[0], 90000000, *self.args[2:], apply=True)

    def test_apply_is_private_bounded_and_preserves_existing_rows(self):
        result = prepare(*self.args, apply=True)
        self.assertEqual(result["work_counts"], {"legacy_project": 4, "solution": 21})
        self.assertEqual(PartnerProgram.objects.filter(draft=True).count(), 2)
        programs = [row["id"] for row in result["programs"]]
        self.assertFalse(
            PartnerProgram.objects.filter(
                pk__in=programs, solution_creation_enabled=True
            ).exists()
        )
        self.assertEqual(ProgramSolution.objects.filter(status="submitted").count(), 3)
        self.assertFalse(ProgramSolution.objects.exclude(published_at=None).exists())
        self.assertEqual(
            PartnerProgramProject.objects.filter(partner_program_id__in=programs).count(),
            4,
        )
        self.assertTrue(
            all(
                not user.has_usable_password()
                for user in get_user_model().objects.filter(
                    pk__in=result["synthetic_user_ids"]
                )
            )
        )
        self.previous_project.refresh_from_db()
        self.assertEqual(self.previous_project.name, "Существующий проект")
        self.assertEqual(getattr(mail, "outbox", []), [])
        with self.assertRaises(ValueError):
            prepare(*self.args, apply=True)

    def test_existing_data_change_rolls_back_the_entire_fixture(self):
        counts = (get_user_model().objects.count(), PartnerProgram.objects.count())

        def corrupt(*args, **kwargs):
            type(self.previous_project).objects.filter(
                pk=self.previous_project.pk
            ).update(name="Ошибка")
            return create_solution(*args, **kwargs)

        with patch("partner_programs.solution_api.create_solution", side_effect=corrupt):
            with self.assertRaisesRegex(AssertionError, "Existing data changed"):
                prepare(*self.args, apply=True)
        self.previous_project.refresh_from_db()
        self.assertEqual(self.previous_project.name, "Существующий проект")
        self.assertEqual(
            (get_user_model().objects.count(), PartnerProgram.objects.count()), counts
        )
