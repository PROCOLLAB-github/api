import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.solution_api import create_solution
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs import solution_team
from partner_programs.tests.helpers import (
    create_program_member,
    create_project,
    create_user,
)
from partner_programs.tests.test_solution_foundation import solution_program
from projects import team_policy, team_service
from projects.models import Collaborator


class TeamFixture:
    def legacy_team(self):
        # Историческая заявка создана до переключения программы в новый режим.
        self.program.solution_storage_mode = "legacy_project"
        self.program.save(update_fields=["solution_storage_mode"])
        project = create_project(leader=self.registered())
        PartnerProgramProject.objects.create(
            partner_program=self.program, project=project
        )
        self.program.solution_storage_mode = "solution"
        self.program.save(update_fields=["solution_storage_mode"])
        return project

    def registered(self, program=None):
        user = create_user()
        create_program_member(program or self.program, user=user)
        return user

    def team(self, program=None):
        program = program or self.program
        captain = self.registered(program)
        obj, _ = create_solution(program.pk, captain, {})
        return obj

    def member(self, solution=None):
        solution = solution or self.solution
        user = self.registered(solution.program)
        ProgramSolutionMember.objects.create(
            solution=solution, user=user, role="Разработчик"
        )
        return user

    def request(self, actor, method, suffix, data=None, *, program=None, solution=None):
        program = program or self.program
        solution = solution or self.solution
        client = APIClient()
        client.force_authenticate(actor)
        return getattr(client, method)(
            f"/programs/{program.pk}/solutions/{solution.pk}/{suffix}",
            {} if data is None else data,
            format="json",
        )

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.data)
        self.assertEqual(response.data["code"], code)
        self.assertEqual(set(response.data), {"code", "detail", "errors", "meta"})


class SolutionTeamTests(TeamFixture, TestCase):
    def setUp(self):
        self.program = solution_program(
            is_competitive=True, legacy_team_min_size=3, legacy_team_max_size=4
        )
        self.solution = self.team()
        self.captain = self.solution.captain
        self.user = self.member()

    def remove(self, actor=None, user=None, version=1):
        user = user or self.user
        return self.request(
            actor or self.captain,
            "delete",
            f"members/{user.pk}/?expected_solution_version={version}",
        )

    def transfer(self, actor=None, user=None, version=1):
        user = user or self.user
        return self.request(
            actor or self.captain,
            "post",
            "captain/",
            {"new_captain_user_id": user.pk, "expected_solution_version": version},
        )

    def freeze(self):
        ProgramSolution.objects.filter(pk=self.solution.pk).update(
            status="submitted", submitted_at=timezone.now(), submission_snapshot={}
        )

    def test_remove_returns_c00_receipt_bumps_version_and_ignores_draft_minimum(self):
        response = self.remove()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["solution_id"], self.solution.pk)
        self.assertEqual(response.data["solution_version"], 2)
        self.assertFalse(self.solution.members.filter(user=self.user).exists())
        self.assertEqual(self.solution.members.get().user_id, self.captain.pk)
        from jsonschema import Draft202012Validator

        contract = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf8")
        )
        Draft202012Validator(
            {
                "$ref": "#/components/schemas/MutationReceipt",
                "components": contract["components"],
            }
        ).validate(response.data)

    def test_removed_user_loses_read_and_current_application(self):
        self.remove()
        self.assert_error(self.request(self.user, "get", ""), 404, "not_found")
        client = APIClient()
        client.force_authenticate(self.user)
        self.assertIsNone(
            client.get(f"/programs/{self.program.pk}/solution-context/").data[
                "current_application"
            ]
        )

    def test_member_can_leave_without_read_response_and_cannot_remove_someone_else(self):
        self.assert_error(self.remove(actor=self.user), 403, "not_solution_captain")
        response = self.request(
            self.user, "post", "leave/", {"expected_solution_version": 1}
        )
        self.assertEqual(response.status_code, 204, response.data)
        self.assertEqual(response.content, b"")
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, 2)
        self.assert_error(self.request(self.user, "get", ""), 404, "not_found")

    def test_captain_cannot_be_removed_or_leave(self):
        self.assert_error(self.remove(user=self.captain), 409, "captain_cannot_leave")
        self.assert_error(
            self.request(
                self.captain, "post", "leave/", {"expected_solution_version": 1}
            ),
            409,
            "captain_cannot_leave",
        )
        self.assertEqual(self.solution.members.count(), 2)

    def test_transfer_keeps_old_captain_and_changes_server_permissions(self):
        response = self.transfer()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["solution_version"], 2)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.captain_id, self.user.pk)
        self.assertEqual(self.solution.members.count(), 2)
        for actor, can_manage in [(self.captain, False), (self.user, True)]:
            detail = self.request(actor, "get", "").data
            self.assertEqual(detail["permissions"]["can_manage_team"], can_manage)
            self.assertEqual(sum(m["is_captain"] for m in detail["team"]["members"]), 1)
            self.assertEqual(detail["team"]["accepted_count"], 2)
        self.assert_error(self.remove(version=2), 403, "not_solution_captain")
        self.assertEqual(
            self.request(
                self.captain, "post", "leave/", {"expected_solution_version": 2}
            ).status_code,
            204,
        )

    def test_transfer_requires_registered_accepted_member(self):
        self.assert_error(
            self.transfer(user=self.captain), 409, "already_solution_captain"
        )
        self.assert_error(self.transfer(user=self.registered()), 409, "member_not_found")
        PartnerProgramUserProfile.objects.filter(
            partner_program=self.program, user=self.user
        ).delete()
        self.assert_error(self.transfer(), 409, "not_program_member")
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.captain_id, self.captain.pk)

    def test_outsider_manager_staff_and_foreign_program_do_not_manage_team(self):
        outsider = self.registered()
        self.assert_error(self.transfer(actor=outsider), 404, "not_found")
        manager = create_user(is_staff=True)
        self.program.managers.add(manager)
        self.assert_error(self.transfer(actor=manager), 403, "not_solution_captain")
        self.assert_error(self.remove(actor=manager), 403, "not_solution_captain")
        self.assert_error(
            self.request(manager, "post", "leave/", {"expected_solution_version": 1}),
            403,
            "not_solution_member",
        )
        other = solution_program()
        self.assert_error(
            self.request(
                self.captain,
                "post",
                "captain/",
                {"new_captain_user_id": self.user.pk, "expected_solution_version": 1},
                program=other,
            ),
            404,
            "not_found",
        )

    def test_stale_version_never_changes_team_and_returns_current_version(self):
        result = self.remove(version=2)
        self.assert_error(result, 409, "version_conflict")
        self.assertEqual(result.data["meta"]["current_version"], 1)
        self.assert_error(self.transfer(version=2), 409, "version_conflict")
        self.assert_error(
            self.request(self.user, "post", "leave/", {"expected_solution_version": 2}),
            409,
            "version_conflict",
        )
        self.assertEqual(self.solution.members.count(), 2)

    def test_submitted_team_rejects_all_commands_and_exposes_no_manage_permission(self):
        self.freeze()
        for response in [
            self.remove(),
            self.transfer(),
            self.request(self.user, "post", "leave/", {"expected_solution_version": 1}),
        ]:
            self.assert_error(response, 409, "team_frozen")
        self.assertFalse(
            self.request(self.captain, "get", "").data["permissions"]["can_manage_team"]
        )
        self.assertEqual(self.solution.members.count(), 2)

    def test_disabled_mode_is_readable_but_cannot_mutate(self):
        self.program.solution_storage_mode = "legacy_project"
        self.program.save()
        self.assert_error(self.remove(), 409, "solution_mode_unavailable")
        self.assert_error(self.transfer(), 409, "solution_mode_unavailable")
        self.assertEqual(self.request(self.captain, "get", "").status_code, 200)

    def test_strict_command_and_query_validation(self):
        for value in [None, True, 1.0, "1", 0, -1]:
            with self.subTest(value=value):
                self.assert_error(
                    self.request(
                        self.user, "post", "leave/", {"expected_solution_version": value}
                    ),
                    400,
                    "validation_error",
                )
        for query in [
            "",
            "?expected_solution_version=1.0",
            "?expected_solution_version=1&user_id=1",
        ]:
            self.assert_error(
                self.request(self.captain, "delete", f"members/{self.user.pk}/{query}"),
                400,
                "validation_error",
            )
        self.assert_error(
            self.request(
                self.user,
                "post",
                "leave/",
                {"expected_solution_version": 1, "solution_id": self.solution.pk},
            ),
            400,
            "validation_error",
        )
        self.assert_error(
            self.request(
                self.captain,
                "post",
                "captain/",
                {"expected_solution_version": 1, "new_captain_user_id": True},
            ),
            400,
            "validation_error",
        )

    def test_missing_and_unsafe_identifiers_are_hidden(self):
        self.assert_error(
            self.request(
                self.captain,
                "delete",
                "members/9007199254740992/?expected_solution_version=1",
            ),
            404,
            "not_found",
        )
        self.assert_error(
            self.request(
                self.captain, "delete", "members/999999999/?expected_solution_version=1"
            ),
            404,
            "not_found",
        )
        self.assertEqual(self.solution.members.count(), 2)

    def test_existing_deadline_does_not_add_a_new_team_restriction(self):
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(days=1)
        )
        self.program.save()
        self.assertEqual(self.remove().status_code, 200)

    def test_reservations_are_unique_and_minimum_uses_only_accepted_users(self):
        pending = self.registered()
        SolutionInvitation.objects.create(solution=self.solution, recipient=pending)
        with transaction.atomic(), self.assertRaises(SolutionError) as error:
            solution_team.validate_submission_team(self.solution)
        self.assertEqual(str(error.exception.get_codes()), "team_min_size")
        detail = self.request(self.captain, "get", "").data["team"]
        self.assertEqual(
            (detail["accepted_count"], detail["pending_count"], detail["reserved_count"]),
            (2, 1, 3),
        )
        with transaction.atomic():
            solution_team.validate_new_member(self.solution, pending.pk)
        self.program.legacy_team_max_size = 3
        self.program.save()
        self.solution.program = self.program
        with transaction.atomic(), self.assertRaises(SolutionError) as error:
            solution_team.validate_new_member(self.solution, self.registered().pk)
        self.assertEqual(str(error.exception.get_codes()), "team_max_size")

    def test_exclusivity_checks_both_owners_and_legacy_model_admin_validation(self):
        project = self.legacy_team()
        with self.assertRaises(ValidationError) as error:
            Collaborator.objects.create(project=project, user=self.user)
        codes = [
            item.code for values in error.exception.error_dict.values() for item in values
        ]
        self.assertIn("already_in_program_team", codes)
        self.assertFalse(
            team_policy.actionable_users(
                project, type(self.user).objects.filter(pk=self.user.pk)
            ).exists()
        )
        legacy_user = self.registered()
        Collaborator.objects.create(project=project, user=legacy_user)
        with transaction.atomic(), self.assertRaises(SolutionError) as error:
            solution_team.validate_new_member(self.solution, legacy_user.pk)
        self.assertEqual(str(error.exception.get_codes()), "already_in_program_team")
        other = self.team()
        with transaction.atomic(), self.assertRaises(SolutionError):
            solution_team.validate_new_member(other, self.captain.pk)

    def test_noncompetitive_finished_and_different_programs_keep_existing_exceptions(
        self,
    ):
        for changes in [
            {"is_competitive": False},
            {"datetime_finished": timezone.now() - timezone.timedelta(days=1)},
        ]:
            for key, value in changes.items():
                setattr(self.program, key, value)
            self.program.save()
            other = self.team()
            with transaction.atomic():
                solution_team.validate_new_member(other, self.user.pk)
            self.program.is_competitive = True
        other_program = solution_program(is_competitive=True)
        create_program_member(other_program, user=self.user)
        other = self.team(other_program)
        with transaction.atomic():
            solution_team.validate_new_member(other, self.user.pk)

    def test_transfer_in_noncompetitive_program_cannot_violate_one_captain_application(
        self,
    ):
        self.program.is_competitive = False
        self.program.save()
        other = self.team()
        ProgramSolutionMember.objects.create(solution=self.solution, user=other.captain)
        self.assert_error(
            self.transfer(user=other.captain), 409, "already_solution_captain"
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.captain_id, self.captain.pk)

    def test_anonymous_cannot_use_any_team_command(self):
        for method, suffix, data in [
            ("delete", f"members/{self.user.pk}/?expected_solution_version=1", {}),
            ("post", "leave/", {"expected_solution_version": 1}),
            (
                "post",
                "captain/",
                {"expected_solution_version": 1, "new_captain_user_id": self.user.pk},
            ),
        ]:
            self.assert_error(
                self.request(None, method, suffix, data), 401, "authentication_required"
            )


@skipUnlessDBFeature("has_select_for_update")
class SolutionTeamConcurrencyTests(TeamFixture, TransactionTestCase):
    def setUp(self):
        self.program = solution_program(is_competitive=True)
        self.solution = self.team()
        self.user = self.member()

    def parallel(self, functions):
        barrier = Barrier(len(functions))

        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                return function()
            except SolutionError as error:
                return str(error.get_codes())
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(run, functions))

    def test_concurrent_captain_commands_only_one_version_succeeds(self):
        another = self.member()

        def transfer(user):
            return solution_team.transfer_captain(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                user_id=user.pk,
                actor=self.solution.captain,
                expected_version=1,
            ).version

        results = self.parallel([lambda: transfer(self.user), lambda: transfer(another)])
        self.assertEqual(results.count(2), 1)
        self.assertEqual(sum(isinstance(result, str) for result in results), 1)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, 2)
        self.assertEqual(self.solution.members.count(), 3)

    def test_same_version_remove_and_leave_do_not_double_apply(self):
        def remove():
            solution_team.remove_member(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                user_id=self.user.pk,
                actor=self.solution.captain,
                expected_version=1,
            )
            return "removed"

        results = self.parallel([remove, remove])
        self.assertCountEqual(results, ["removed", "version_conflict"])

    def test_solution_and_legacy_admission_share_program_lock(self):
        candidate = self.registered()
        project = self.legacy_team()

        def solution_admission():
            # Будущий accept BE03 обязан использовать эту же policy под lock_solution.
            with transaction.atomic():
                obj = solution_team.lock_solution(
                    self.program.pk, self.solution.pk, self.solution.captain
                )
                solution_team.validate_new_member(obj, candidate.pk)
                ProgramSolutionMember.objects.create(solution=obj, user=candidate)
            return "solution"

        def legacy_admission():
            try:
                team_service.add_member(
                    project_id=project.pk, user_id=candidate.pk, actor=project.leader
                )
                return "legacy"
            except Exception as error:
                from projects.team_errors import TeamError

                if isinstance(error, TeamError):
                    return str(error.detail["code"])
                raise

        results = self.parallel([solution_admission, legacy_admission])
        self.assertEqual(results.count("already_in_program_team"), 1)
        self.assertEqual(
            ProgramSolutionMember.objects.filter(user=candidate).count()
            + Collaborator.objects.filter(user=candidate).count(),
            1,
        )
