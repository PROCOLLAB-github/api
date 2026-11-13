from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib import admin
from django.db import connection
from django.test import RequestFactory, TestCase

from partner_programs.models import PartnerProgram
from project_rates.program_experts import can_evaluate_program, program_experts
from project_rates.tests.helpers import (
    create_rate_expert,
    create_rate_program,
    create_rate_user,
)
from users.models import CustomUser, Expert


class OrganizerEvaluationBackfillTests(TestCase):
    def test_django_admin_manager_save_grants_access_without_role_or_assignment_changes(
        self,
    ):
        program = create_rate_program()
        organizer = create_rate_user()
        staff = create_rate_user()
        staff.is_staff = staff.is_superuser = True
        staff.save(update_fields=["is_staff", "is_superuser"])
        request = RequestFactory().post("/admin/partner_programs/partnerprogram/")
        request.user = staff
        registered = admin.site._registry[PartnerProgram]
        form_class = registered.get_form(request, program, fields=["managers"])
        form = form_class(data={"managers": [organizer.pk]}, instance=program)
        self.assertTrue(form.is_valid(), form.errors)
        instance = form.save(commit=False)
        registered.save_model(request, instance, form, change=True)
        registered.save_related(request, form, [], change=True)
        organizer.refresh_from_db()
        self.assertEqual(organizer.user_type, CustomUser.MEMBER)
        self.assertFalse(organizer.is_staff)
        self.assertTrue(can_evaluate_program(organizer, program.pk))
        self.assertFalse(organizer.expert.project_assignments.exists())
        self.assertFalse(organizer.expert.programs.exists())

    def test_existing_manager_is_backfilled_without_changing_roles_or_independent_grants(
        self,
    ):
        program = create_rate_program()
        organizer = create_rate_user()
        independent = create_rate_expert(program=program)
        original_expert_id = independent.expert.pk
        outsider = create_rate_user()
        # Historical through-table rows did not provision Expert identities.
        relation = PartnerProgram.managers.through
        relation.objects.bulk_create(
            [
                relation(partnerprogram=program, customuser=user)
                for user in (organizer, independent)
            ]
        )
        self.assertTrue(can_evaluate_program(organizer, program.pk))
        self.assertFalse(Expert.objects.filter(user=organizer).exists())

        migration = import_module(
            "partner_programs.migrations.0044_organizer_expert_identities"
        )
        editor = SimpleNamespace(connection=connection)
        migration.create_organizer_expert_identities(apps, editor)
        migration.create_organizer_expert_identities(apps, editor)

        self.assertCountEqual(
            program_experts(program.pk).values_list("user_id", flat=True),
            [organizer.pk, independent.pk],
        )
        organizer.refresh_from_db()
        self.assertEqual(organizer.user_type, CustomUser.MEMBER)
        self.assertFalse(organizer.expert.programs.exists())
        self.assertTrue(program.experts.filter(pk=original_expert_id).exists())
        self.assertFalse(Expert.objects.filter(user=outsider).exists())
