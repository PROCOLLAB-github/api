from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from partner_programs.permissions import IsAdminOrManagerOfProgram, IsProjectLeader
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_project,
    create_project,
    create_user,
)


class PartnerProgramPermissionTests(TestCase):
    def test_admin_or_manager_permission_allows_program_manager(self):
        manager = create_user(prefix="program-permission-manager")
        program = create_partner_program()
        program.managers.add(manager)
        request = SimpleNamespace(user=manager)
        view = SimpleNamespace(kwargs={"pk": program.id})

        self.assertTrue(IsAdminOrManagerOfProgram().has_permission(request, view))

    def test_admin_or_manager_permission_allows_staff_user(self):
        staff_user = create_user(prefix="program-permission-staff", is_staff=True)
        request = SimpleNamespace(user=staff_user)
        view = SimpleNamespace(kwargs={"pk": 999999})

        self.assertTrue(IsAdminOrManagerOfProgram().has_permission(request, view))

    def test_admin_or_manager_permission_rejects_outsider(self):
        outsider = create_user(prefix="program-permission-outsider")
        program = create_partner_program()
        request = SimpleNamespace(user=outsider)
        view = SimpleNamespace(kwargs={"pk": program.id})

        self.assertFalse(IsAdminOrManagerOfProgram().has_permission(request, view))

    def test_admin_or_manager_permission_rejects_anonymous_user(self):
        request = SimpleNamespace(user=AnonymousUser())
        view = SimpleNamespace(kwargs={"pk": 1})

        self.assertFalse(IsAdminOrManagerOfProgram().has_permission(request, view))

    def test_project_leader_permission_allows_project_leader(self):
        leader = create_user(prefix="program-permission-leader")
        project = create_project(leader=leader)
        program_project = create_program_project(
            create_partner_program(),
            project=project,
        )
        request = SimpleNamespace(user=leader)

        self.assertTrue(
            IsProjectLeader().has_object_permission(request, None, program_project)
        )

    def test_project_leader_permission_rejects_non_leader(self):
        leader = create_user(prefix="program-permission-leader")
        outsider = create_user(prefix="program-permission-not-leader")
        project = create_project(leader=leader)
        program_project = create_program_project(
            create_partner_program(),
            project=project,
        )
        request = SimpleNamespace(user=outsider)

        self.assertFalse(
            IsProjectLeader().has_object_permission(request, None, program_project)
        )
