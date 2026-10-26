import copy
import json
from pathlib import Path
from time import time
from unittest.mock import patch

from django.core import signing
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.services import (
    solution_case_actions,
    solution_member_actions as actions,
)
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionMember,
    SolutionAdministrativeChange,
    SolutionInvitation,
)
from partner_programs.solution_submission import submit_solution
from partner_programs.tests.helpers import (
    create_user,
    create_program_member,
    create_partner_program,
)
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_submission import SubmissionFixture
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.tests.helpers import create_rate_criteria, create_rate_expert
from projects.models import Project

FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class MemberFixture(SubmissionFixture):
    def setUp(self):
        self.ready()
        self.member = create_user()
        self.registration = create_program_member(self.program, user=self.member)
        self.membership = ProgramSolutionMember.objects.create(
            solution=self.solution, user=self.member, role="Backend-разработчик"
        )
        self.invitation = SolutionInvitation.objects.create(
            solution=self.solution,
            recipient=self.member,
            role=self.membership.role,
            status="accepted",
        )
        self.member_root = f"/programs/{self.program.pk}/management/solutions/{self.solution.pk}/members/remove/"
        self.history = f"/programs/{self.program.pk}/management/solutions/{self.solution.pk}/history/"

    def preview(self, actor=None, user_id=None):
        return call(
            actor or self.manager,
            "post",
            self.member_root + "preview/",
            dict(user_id=self.member.pk if user_id is None else user_id),
        )

    def submit(self, **changes):
        response = super().submit(**changes)
        self.solution.refresh_from_db()
        return response

    def removal_command(self):
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["can_apply"], response.data)
        return dict(user_id=self.member.pk, preview_token=response.data["preview_token"])

    def apply(self, command, actor=None):
        return call(actor or self.manager, "post", self.member_root + "apply/", command)

    def wire(self, response, status=200, schema="SolutionMemberRemovalPreview"):
        self.assertEqual(response.status_code, status, response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(
            {
                "components": spec["components"],
                "$ref": "#/components/schemas/" + (schema if status == 200 else "Error"),
            },
            format_checker=FormatChecker(),
        ).validate(response.data)
        return response.data

    def saved(self):
        self.solution.refresh_from_db()
        return dict(
            solution=list(ProgramSolution.objects.filter(pk=self.solution.pk).values()),
            members=list(self.solution.members.order_by("pk").values()),
            invitations=list(self.solution.invitations.order_by("pk").values()),
            answers=list(self.solution.answers.order_by("pk").values()),
            assignments=list(self.solution.expert_assignments.order_by("pk").values()),
            scores=list(self.solution.scores.order_by("pk").values()),
            registrations=list(
                PartnerProgramUserProfile.objects.filter(partner_program=self.program)
                .order_by("pk")
                .values()
            ),
            projects=list(Project.objects.order_by("pk").values()),
        )

    def evaluation(self):
        self.assertEqual(self.submit().status_code, 200)
        self.expert = create_rate_expert(program=self.program)
        self.assignment = SolutionExpertAssignment.objects.create(
            partner_program=self.program,
            solution=self.solution,
            expert=self.expert.expert,
        )
        self.criterion = create_rate_criteria(self.program, min_value=0, max_value=10)
        self.score = SolutionScore.objects.create(
            solution=self.solution, criteria=self.criterion, user=self.expert, value="0"
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionMemberActionTests(MemberFixture, TestCase):
    def test_preview_is_read_only_and_binds_exact_actor_program_solution_user(self):
        before = self.saved()
        result = self.wire(self.preview())
        self.assertEqual(result["member"]["user"]["id"], self.member.pk)
        self.assertEqual(result["member"]["role"], "Backend-разработчик")
        self.assertEqual(result["remaining_member_count"], 1)
        self.assertFalse(result["is_submitted"])
        proof = signing.loads(result["preview_token"], salt=actions.SALT)
        self.assertEqual(
            {k: proof[k] for k in ("actor", "program", "solution", "user")},
            dict(
                actor=self.manager.pk,
                program=self.program.pk,
                solution=self.solution.pk,
                user=self.member.pk,
            ),
        )
        self.assertEqual(self.saved(), before)

    def test_draft_removal_preserves_registration_answers_processed_invite_and_other_solution(
        self,
    ):
        other_program = create_partner_program(name="Другая программа")
        other = ProgramSolution.objects.create(program=other_program, captain=self.member)
        other_member = ProgramSolutionMember.objects.create(
            solution=other, user=self.member
        )
        pending = SolutionInvitation.objects.create(
            solution=self.solution, recipient=self.member, role="Новая роль"
        )
        unrelated = SolutionInvitation.objects.create(
            solution=self.solution, recipient=create_user(), role="Дизайнер"
        )
        before = self.saved()
        preview = self.wire(self.preview())
        self.assertEqual(preview["revoked_invitation_count"], 1)
        result = self.wire(
            self.apply(
                dict(user_id=self.member.pk, preview_token=preview["preview_token"])
            ),
            schema="MutationReceipt",
        )
        after = self.saved()
        self.assertEqual(result["solution_version"], before["solution"][0]["version"] + 1)
        for key in ("answers", "registrations", "projects", "scores", "assignments"):
            self.assertEqual(after[key], before[key])
        self.assertFalse(self.solution.members.filter(user=self.member).exists())
        self.assertFalse(SolutionInvitation.objects.filter(pk=pending.pk).exists())
        self.assertTrue(
            SolutionInvitation.objects.filter(
                pk=self.invitation.pk, status="accepted"
            ).exists()
        )
        self.assertTrue(
            SolutionInvitation.objects.filter(pk=unrelated.pk, status="pending").exists()
        )
        self.assertTrue(ProgramSolutionMember.objects.filter(pk=other_member.pk).exists())
        change = self.solution.administrative_changes.get()
        self.assertEqual(change.revoked_invitation_ids, [pending.pk])
        self.assertIsNone(change.before_snapshot)
        self.assertEqual(change.removed_member, preview["member"])
        self.assertEqual(call(self.member, "get", self.url).status_code, 404)
        self.assertEqual(
            call(
                self.member, "get", f"/solution-invitations/{self.invitation.pk}/"
            ).status_code,
            200,
        )

    def test_submitted_removal_changes_only_snapshot_members_and_keeps_evaluation(self):
        self.program.legacy_team_min_size = 2
        self.program.save()
        self.evaluation()
        before = self.saved()
        original = copy.deepcopy(self.solution.submission_snapshot)
        preview = self.wire(self.preview())
        self.assertTrue(preview["is_submitted"])
        self.assertEqual(preview["score_count"], 1)
        self.wire(
            self.apply(
                dict(user_id=self.member.pk, preview_token=preview["preview_token"])
            ),
            schema="MutationReceipt",
        )
        after = self.saved()
        expected = copy.deepcopy(original)
        expected["members"] = [
            m for m in original["members"] if m["user"]["id"] != self.member.pk
        ]
        self.assertEqual(self.solution.submission_snapshot, expected)
        for key in (
            "answers",
            "registrations",
            "projects",
            "scores",
            "assignments",
            "invitations",
        ):
            self.assertEqual(after[key], before[key])
        for key, value in before["solution"][0].items():
            if key not in ("version", "updated_at", "submission_snapshot"):
                self.assertEqual(after["solution"][0][key], value)
        detail = self.wire(
            call(
                self.manager,
                "get",
                self.history + str(self.solution.administrative_changes.get().pk) + "/",
            ),
            schema="SolutionAdminChangeDetail",
        )
        self.assertEqual(detail["before_snapshot"], original)
        self.assertEqual(detail["after_snapshot"], expected)
        self.assertEqual(detail["change"]["action"], "remove_member")
        self.assertEqual(detail["change"]["removed_member"], preview["member"])
        current = call(self.captain, "get", self.url)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.data["team"]["accepted_count"], 1)
        self.assertTrue(current.data["team"]["is_frozen"])
        self.assertEqual(call(self.member, "get", self.url).status_code, 404)

    def test_captain_is_visible_in_preview_but_cannot_be_removed(self):
        for submitted in (False, True):
            with self.subTest(submitted=submitted):
                if submitted:
                    self.assertEqual(self.submit().status_code, 200)
                before = self.saved()
                result = self.wire(self.preview(user_id=self.captain.pk))
                self.assertFalse(result["can_apply"])
                self.assertIsNone(result["preview_token"])
                self.assertEqual(result["errors"][0]["code"], "captain_cannot_be_removed")
                token = signing.dumps(
                    {
                        **actions.proof_context(
                            self.program, self.solution, self.manager, self.captain.pk
                        ),
                        "state": "not-valid",
                    },
                    salt=actions.SALT,
                )
                self.wire(
                    self.apply(dict(user_id=self.captain.pk, preview_token=token)), 409
                )
                self.assertEqual(self.saved(), before)

    def test_deadline_creation_switch_and_unconfigured_form_do_not_block_manager_removal(
        self,
    ):
        self.assertEqual(self.submit().status_code, 200)
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_creation_enabled=False,
            solution_template=None,
            datetime_project_submission_ends=timezone.now() - timezone.timedelta(days=1),
        )
        self.wire(self.apply(self.removal_command()), schema="MutationReceipt")
        self.assertFalse(self.solution.members.filter(user=self.member).exists())

    def test_noncompetitive_saved_materials_remain_draft_without_artificial_submission(
        self,
    ):
        PartnerProgram.objects.filter(pk=self.program.pk).update(is_competitive=False)
        self.wire(self.apply(self.removal_command()), schema="MutationReceipt")
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.status, "draft")
        self.assertIsNone(self.solution.submitted_at)
        self.assertIsNone(self.solution.submission_snapshot)

    def test_ordinary_delete_leave_and_model_writes_stay_frozen_after_exception(self):
        extra_user = create_user()
        create_program_member(self.program, user=extra_user)
        extra = ProgramSolutionMember.objects.create(
            solution=self.solution, user=extra_user
        )
        self.assertEqual(self.submit().status_code, 200)
        self.wire(self.apply(self.removal_command()), schema="MutationReceipt")
        before = self.saved()
        with self.assertRaises(ProtectedError), transaction.atomic():
            extra.delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.solution.members.filter(pk=extra.pk).delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.solution.delete()
        result = call(
            self.captain,
            "delete",
            self.url
            + f"members/{extra.user_id}/?expected_solution_version={self.solution.version}",
        )
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.data["code"], "team_frozen")
        self.assertEqual(self.saved(), before)

    def test_journal_failure_rolls_back_member_pending_snapshot_version_and_scoped_permission(
        self,
    ):
        self.evaluation()
        pending = SolutionInvitation.objects.bulk_create(
            [
                SolutionInvitation(
                    solution=self.solution, recipient=self.member, role="Дизайнер"
                )
            ]
        )[0]
        command = self.removal_command()
        before = self.saved()
        with patch.object(
            SolutionAdministrativeChange.objects,
            "create",
            side_effect=RuntimeError("journal unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                actions.apply(self.program.pk, self.solution.pk, self.manager, command)
        self.assertEqual(self.saved(), before)
        self.assertTrue(SolutionInvitation.objects.filter(pk=pending.pk).exists())
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.membership.delete()
        self.assertEqual(self.solution.administrative_changes.count(), 0)

    def test_replay_bad_signature_expiry_and_foreign_action_do_not_write(self):
        command = self.removal_command()
        before = self.saved()
        for token in (
            "not-a-token",
            signing.dumps([], salt=actions.SALT),
            signing.dumps({}, salt=solution_case_actions.SALT),
        ):
            self.wire(self.apply({**command, "preview_token": token}), 409)
        with patch("django.core.signing.time.time", return_value=time() - 601):
            expired = self.removal_command()
        self.wire(self.apply(expired), 409)
        self.assertEqual(self.saved(), before)
        self.wire(self.apply(command), schema="MutationReceipt")
        after = self.saved()
        self.assertEqual(
            self.wire(self.apply(command), 409)["code"], "solution_action_conflict"
        )
        self.assertEqual(self.saved(), after)
        self.assertEqual(self.solution.administrative_changes.count(), 1)

    def test_actor_target_and_solution_binding_are_rechecked(self):
        command = self.removal_command()
        self.wire(self.apply(command, actor=create_user(is_staff=True)), 409)
        self.wire(self.apply({**command, "user_id": self.captain.pk}), 409)
        other = ProgramSolution.objects.create(
            program=self.program, captain=create_user()
        )
        path = f"/programs/{self.program.pk}/management/solutions/{other.pk}/members/remove/apply/"
        self.wire(call(self.manager, "post", path, command), 409)
        self.assertEqual(self.solution.administrative_changes.count(), 0)

    def test_direct_data_and_score_changes_without_version_bump_invalidate_confirmation(
        self,
    ):
        self.evaluation()
        changes = [
            lambda: self.solution.members.filter(user=self.member).update(
                role="Новая роль"
            ),
            lambda: self.solution.answers.filter(
                field_id=self.fields["number"]["id"]
            ).update(value=9),
            lambda: self.solution.scores.filter(pk=self.score.pk).update(value="8"),
            lambda: self.solution.invitations.filter(pk=self.invitation.pk).update(
                role="Иная роль"
            ),
        ]
        for change in changes:
            with self.subTest(change=change), transaction.atomic():
                command = self.removal_command()
                change()
                before = self.saved()
                self.wire(self.apply(command), 409)
                self.assertEqual(self.saved(), before)
                transaction.set_rollback(True)

    def test_permissions_scope_and_legacy_mode_are_checked_before_members(self):
        for actor, status in (
            (None, 401),
            (self.captain, 403),
            (self.member, 403),
            (create_user(), 403),
        ):
            self.wire(
                call(
                    actor,
                    "post",
                    self.member_root + "preview/",
                    dict(user_id=self.member.pk),
                ),
                status,
            )
        other = create_partner_program(
            name="Чужая программа", solution_storage_mode="solution"
        )
        path = f"/programs/{other.pk}/management/solutions/{self.solution.pk}/members/remove/preview/"
        self.wire(
            call(create_user(is_staff=True), "post", path, dict(user_id=self.member.pk)),
            404,
        )
        self.wire(self.preview(user_id=9007199254740991), 404)
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_storage_mode="legacy_project"
        )
        self.assertEqual(
            self.wire(self.preview(), 409)["code"], "solution_mode_unavailable"
        )

    def test_permissions_are_rechecked_when_manager_role_is_revoked(self):
        command = self.removal_command()
        self.program.managers.remove(self.manager)
        self.wire(self.apply(command), 403)
        self.assertTrue(self.solution.members.filter(user=self.member).exists())

    def test_strict_body_query_and_exact_safe_integer_validation(self):
        for body in (
            {},
            {"user_id": True},
            {"user_id": "1"},
            {"user_id": 0},
            {"user_id": 1.5},
            {"user_id": 2**53},
            {"user_id": self.member.pk, "project_id": 1},
        ):
            self.wire(
                call(self.manager, "post", self.member_root + "preview/", body), 400
            )
        self.wire(
            call(
                self.manager,
                "post",
                self.member_root + "preview/?all=true",
                dict(user_id=self.member.pk),
            ),
            400,
        )
        for token in (None, True, 7, ""):
            self.wire(self.apply(dict(user_id=self.member.pk, preview_token=token)), 400)
        self.wire(self.apply(dict(user_id=self.member.pk)), 400)

    def test_case_and_member_history_coexist_without_rewriting_case_payload(self):
        field = self.program.fields.get(pk=self.fields["select"]["id"])
        field.solution_options = ["Задача 1", "Задача 2"]
        field.save()
        data = solution_case_actions.preview(
            self.program.pk, self.solution.pk, self.manager, dict(case_name="Задача 2")
        )
        solution_case_actions.apply(
            self.program.pk,
            self.solution.pk,
            self.manager,
            dict(case_name="Задача 2", preview_token=data["preview_token"]),
        )
        case = self.solution.administrative_changes.get()
        original = call(self.manager, "get", self.history + str(case.pk) + "/").data
        self.wire(self.apply(self.removal_command()), schema="MutationReceipt")
        listing = self.wire(
            call(self.manager, "get", self.history), schema="SolutionAdminChangePage"
        )
        self.assertEqual(
            [r["action"] for r in listing["results"]], ["remove_member", "change_case"]
        )
        self.assertEqual(
            call(self.manager, "get", self.history + str(case.pk) + "/").data, original
        )
        self.assertNotIn("removed_member", original["change"])


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionMemberActionConcurrencyTests(MemberFixture, TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL program locks")
        super().setUp()

    def race(self, commands):
        # The shared observed-wait helper proves both worker backends are blocked
        # by the controller's program lock before allowing either writer through.
        from partner_programs.tests.test_solution_case_actions import (
            SolutionCaseActionConcurrencyTests,
        )

        return SolutionCaseActionConcurrencyTests.race(self, commands)

    def test_two_submitted_confirmations_remove_once_and_keep_original_snapshot(self):
        self.assertEqual(self.submit().status_code, 200)
        original = copy.deepcopy(self.solution.submission_snapshot)
        command = self.removal_command()

        def remove():
            return actions.apply(self.program.pk, self.solution.pk, self.manager, command)

        self.assertCountEqual(
            self.race([remove, remove]), ["saved", "solution_action_conflict"]
        )
        self.solution.refresh_from_db()
        self.assertFalse(self.solution.members.filter(user=self.member).exists())
        self.assertEqual(
            self.solution.administrative_changes.get().before_snapshot, original
        )

    def test_removal_and_submission_keep_one_version_and_coherent_roster(self):
        command = self.removal_command()
        submit = self.command()
        version = self.solution.version

        def remove():
            return actions.apply(self.program.pk, self.solution.pk, self.manager, command)

        def send():
            return submit_solution(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=self.captain,
                **submit,
            )

        result = self.race([remove, send])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, version + 1)
        if result[0] == "saved":
            self.assertEqual(result, ["saved", "version_conflict"])
            self.assertEqual(self.solution.status, "draft")
            self.assertEqual(self.solution.members.count(), 1)
        else:
            self.assertEqual(result, ["solution_action_conflict", "saved"])
            self.assertEqual(self.solution.status, "submitted")
            self.assertEqual(len(self.solution.submission_snapshot["members"]), 2)

    def test_submitted_removal_and_score_update_preserve_scoring(self):
        self.evaluation()
        command = self.removal_command()
        before = copy.deepcopy(self.solution.submission_snapshot)

        def remove():
            return actions.apply(self.program.pk, self.solution.pk, self.manager, command)

        def rate():
            self.score.value = "7"
            self.score.save()

        result = self.race([remove, rate])
        self.score.refresh_from_db()
        self.solution.refresh_from_db()
        self.assertEqual(self.score.value, "7")
        self.assertEqual(result[1], "saved")
        self.assertTrue(
            SolutionExpertAssignment.objects.filter(pk=self.assignment.pk).exists()
        )
        if result[0] == "saved":
            self.assertEqual(
                self.solution.administrative_changes.get().before_snapshot, before
            )
            self.assertFalse(self.solution.members.filter(user=self.member).exists())
        else:
            self.assertEqual(result[0], "solution_action_conflict")
            self.assertEqual(self.solution.submission_snapshot, before)
