from io import BytesIO

from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import Criteria, ProjectScore


PROFILE_EXPORT = "admin:export_profiles"
SCORE_EXPORT = "admin:partner_programs_export_rates"
MAILING = "admin:partner_programs_mailing"
PROGRAM_ACTIONS = (PROFILE_EXPORT, SCORE_EXPORT, MAILING)


class PartnerProgramAdminActionAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.program = create_partner_program()
        cls.other_program = create_partner_program()
        cls.staff = create_user(is_staff=True, is_active=True)
        cls.manager = create_user(is_staff=True, is_active=True)
        cls.superuser = create_user(is_staff=True, is_active=True, is_superuser=True)
        cls.program.managers.add(cls.manager)
        manager_group, _ = Group.objects.get_or_create(name="Руководитель программы")
        cls.manager.groups.add(manager_group)

        cls.member = create_program_member(cls.program).user
        cls.other_member = create_program_member(cls.other_program).user
        cls.project = create_project()
        create_program_project(cls.program, project=cls.project)
        criterion = Criteria.objects.create(
            partner_program=cls.program, name="Оценка проекта", type="str"
        )
        ProjectScore.objects.create(
            criteria=criterion, user=cls.manager, project=cls.project, value="9"
        )

    def grant_program_permission(self, user, codename):
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="partner_programs", codename=codename
            )
        )

    def assert_program_actions_status(self, program_id, status):
        for action in PROGRAM_ACTIONS:
            with self.subTest(action=action, program_id=program_id):
                response = self.client.get(reverse(action, args=[program_id]))
                self.assertEqual(response.status_code, status)
                self.assertNotIn("Content-Disposition", response)

    def exported_cells(self, action, program_id):
        response = self.client.get(reverse(action, args=[program_id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(".xlsx", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        try:
            return {
                cell for row in workbook.active.iter_rows(values_only=True) for cell in row
            }
        finally:
            workbook.close()

    def test_staff_without_model_permission_cannot_use_program_actions(self):
        self.client.force_login(self.staff)
        self.assert_program_actions_status(self.program.pk, 403)
        self.assert_program_actions_status(0, 403)

    def test_manager_with_view_permission_can_export_own_program(self):
        self.grant_program_permission(self.manager, "view_partnerprogram")
        self.client.force_login(self.manager)

        profiles = self.exported_cells(PROFILE_EXPORT, self.program.pk)
        self.assertIn(self.member.email, profiles)
        self.assertNotIn(self.other_member.email, profiles)
        scores = self.exported_cells(SCORE_EXPORT, self.program.pk)
        self.assertIn(self.project.name, scores)
        self.assertIn("9", scores)
        response = self.client.get(reverse(MAILING, args=[self.program.pk]))
        self.assertEqual(response.status_code, 403)

    def test_manager_with_change_permission_is_limited_to_own_program(self):
        self.grant_program_permission(self.manager, "change_partnerprogram")
        self.client.force_login(self.manager)

        self.assertIn(
            self.member.email, self.exported_cells(PROFILE_EXPORT, self.program.pk)
        )
        self.assertIn(self.project.name, self.exported_cells(SCORE_EXPORT, self.program.pk))
        self.assertContains(
            self.client.get(reverse(MAILING, args=[self.program.pk])),
            "Рассылка недоступна.",
            status_code=503,
        )
        self.assert_program_actions_status(self.other_program.pk, 404)
        self.assert_program_actions_status(0, 404)

    def test_superuser_can_access_other_program(self):
        self.client.force_login(self.superuser)

        self.assertIn(
            self.other_member.email,
            self.exported_cells(PROFILE_EXPORT, self.other_program.pk),
        )
        self.assertNotIn(
            self.project.name, self.exported_cells(SCORE_EXPORT, self.other_program.pk)
        )
        self.assertContains(
            self.client.get(reverse(MAILING, args=[self.other_program.pk])),
            "Рассылка недоступна.",
            status_code=503,
        )
        self.assert_program_actions_status(0, 404)
