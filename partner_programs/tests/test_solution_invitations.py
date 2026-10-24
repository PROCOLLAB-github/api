import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs import solution_invitations, solution_team
from partner_programs.models import PartnerProgramUserProfile
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs.tests.helpers import create_user, create_program_member
from partner_programs.tests.test_solution_foundation import solution_program
from partner_programs.tests.test_solution_team import TeamFixture


def call(actor, method, url, data=None):
    client = APIClient()
    client.force_authenticate(actor)
    return getattr(client, method)(url, {} if data is None else data, format="json")


class InvitationFixture(TeamFixture):
    def seed(self):
        self.program = solution_program(is_competitive=True, legacy_team_max_size=3)
        self.solution = self.team()
        self.captain = self.solution.captain
        self.recipient = self.registered()
        self.root = (
            f"/programs/{self.program.pk}/solutions/{self.solution.pk}/invitations/"
        )

    def create(self, recipient=None, **fields):
        self.solution.refresh_from_db()
        return call(
            self.captain,
            "post",
            self.root,
            dict(
                expected_solution_version=self.solution.version,
                recipient_user_id=(recipient or self.recipient).pk,
                role="Аналитик",
                specialization="Данные",
                motivational_letter="Присоединяйтесь",
                **fields,
            ),
        )

    def invite(self, recipient=None):
        result = self.create(recipient)
        self.assertEqual(result.status_code, 201, result.data)
        return result.data["invitation"]

    def action(self, invite, actor=None, decision="accept", version=None):
        return call(
            actor or self.recipient,
            "post",
            f"/solution-invitations/{invite['id']}/{decision}/",
            {"expected_version": invite["version"] if version is None else version},
        )

    def validate_schema(self, response, name):
        from jsonschema import Draft202012Validator

        contract = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf8")
        )
        Draft202012Validator(
            {"$ref": "#/components/schemas/" + name, "components": contract["components"]}
        ).validate(response.data)


class SolutionInvitationTests(InvitationFixture, TestCase):
    def setUp(self):
        self.seed()

    def test_create_accept_and_read_use_c00_without_project_or_independent_team(self):
        result = self.create()
        self.validate_schema(result, "InvitationCreated")
        invite = result.data["invitation"]
        self.assertEqual(result.data["solution_version"], 2)
        self.assertTrue(invite["permissions"]["can_edit"])
        self.assertEqual(self.solution.members.count(), 1)
        self.assert_error(
            call(
                self.recipient,
                "get",
                f"/programs/{self.program.pk}/solutions/{self.solution.pk}/",
            ),
            404,
            "not_found",
        )
        detail = call(self.recipient, "get", f"/solution-invitations/{invite['id']}/")
        self.validate_schema(detail, "Invitation")
        self.assertTrue(detail.data["permissions"]["can_accept"])
        self.assertNotIn("answers", detail.data)
        self.assertNotIn("team", detail.data["solution"])
        accepted = self.action(invite)
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.validate_schema(accepted, "InvitationActionResult")
        self.assertEqual(accepted.data["solution_version"], 3)
        self.assertEqual(accepted.data["application"]["solution_id"], self.solution.pk)
        self.assertEqual(accepted.data["invitation"]["version"], 2)
        member = self.solution.members.get(user=self.recipient)
        self.assertEqual((member.role, member.specialization), ("Аналитик", "Данные"))
        self.assertEqual(self.solution.members.count(), 2)
        self.assertFalse(any(accepted.data["invitation"]["permissions"].values()))
        current = call(
            self.recipient, "get", f"/programs/{self.program.pk}/solution-context/"
        )
        self.assertEqual(
            current.data["current_application"]["solution_id"], self.solution.pk
        )

    def test_inbox_and_solution_list_are_scoped_and_paginated(self):
        first = self.invite()
        self.invite(self.registered())
        inbox = call(self.recipient, "get", "/solution-invitations/?limit=1")
        self.validate_schema(inbox, "InvitationPage")
        self.assertEqual(inbox.data["count"], 1)
        self.assertEqual(inbox.data["results"][0]["id"], first["id"])
        sent = call(self.captain, "get", self.root + "?limit=1")
        self.validate_schema(sent, "InvitationPage")
        self.assertEqual(sent.data["count"], 2)
        self.assertIsNotNone(sent.data["next"])
        self.assertEqual(sent.data["results"][0]["id"], first["id"])
        self.assertEqual(
            call(self.captain, "get", "/solution-invitations/").data["count"], 0
        )
        self.assert_error(call(self.recipient, "get", self.root), 404, "not_found")
        self.action(first)
        self.assert_error(
            call(self.recipient, "get", self.root), 403, "not_solution_captain"
        )

    def test_recipient_cannot_mutate_as_captain_and_other_roles_cannot_read_invite(self):
        invite = self.invite()
        url = f"/solution-invitations/{invite['id']}/"
        for other in [self.registered(), create_user(is_staff=True)]:
            self.program.managers.add(other)
            self.assert_error(call(other, "get", url), 404, "not_found")
            self.assert_error(
                call(
                    other,
                    "patch",
                    url,
                    {"expected_version": 1, "expected_solution_version": 2, "role": "X"},
                ),
                404,
                "not_found",
            )
        self.assert_error(
            call(
                self.recipient,
                "patch",
                url,
                {"expected_version": 1, "expected_solution_version": 2, "role": "X"},
            ),
            403,
            "not_solution_captain",
        )
        self.assert_error(
            self.action(invite, actor=self.captain), 403, "not_invite_recipient"
        )

    def test_patch_changes_only_fields_and_both_versions(self):
        invite = self.invite()
        result = call(
            self.captain,
            "patch",
            f"/solution-invitations/{invite['id']}/",
            {
                "expected_version": 1,
                "expected_solution_version": 2,
                "role": None,
                "motivational_letter": "",
            },
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.validate_schema(result, "InvitationCreated")
        self.assertIsNone(result.data["invitation"]["role"])
        self.assertEqual(result.data["invitation"]["specialization"], "Данные")
        self.assertEqual(result.data["solution_version"], 3)
        self.assertEqual(result.data["invitation"]["version"], 2)

    def test_revoke_requires_both_versions_and_deletes_only_pending(self):
        invite = self.invite()
        url = f"/solution-invitations/{invite['id']}/"
        self.assert_error(
            call(
                self.captain,
                "delete",
                url + "?expected_version=1&expected_solution_version=1",
            ),
            409,
            "version_conflict",
        )
        result = call(
            self.captain,
            "delete",
            url + "?expected_version=1&expected_solution_version=2",
        )
        self.assertEqual(result.status_code, 204)
        self.assertFalse(SolutionInvitation.objects.exists())
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, 3)
        self.assertEqual(self.solution.members.count(), 1)

    def test_stale_invitation_or_solution_version_has_no_partial_write(self):
        invite = self.invite()
        self.assert_error(self.action(invite, version=2), 409, "version_conflict")
        self.assert_error(
            call(
                self.captain,
                "patch",
                f"/solution-invitations/{invite['id']}/",
                {"expected_version": 2, "expected_solution_version": 2, "role": "X"},
            ),
            409,
            "version_conflict",
        )
        self.assert_error(
            call(
                self.captain,
                "patch",
                f"/solution-invitations/{invite['id']}/",
                {"expected_version": 1, "expected_solution_version": 1, "role": "X"},
            ),
            409,
            "version_conflict",
        )
        obj = SolutionInvitation.objects.get()
        self.assertEqual((obj.version, obj.role, obj.status), (1, "Аналитик", "pending"))
        self.assertEqual(self.solution.members.count(), 1)

    def test_duplicate_and_accepted_member_do_not_consume_new_reserve(self):
        invite = self.invite()
        self.assert_error(self.create(), 409, "duplicate_pending_invite")
        self.assert_error(self.create(self.captain), 409, "already_solution_member")
        self.action(invite)
        self.assert_error(self.create(), 409, "already_solution_member")
        self.assertEqual(self.solution.invitations.count(), 1)

    def test_maximum_includes_pending_but_accept_uses_own_reserved_place(self):
        self.program.legacy_team_max_size = 2
        self.program.save()
        invite = self.invite()
        self.assert_error(self.create(self.registered()), 409, "team_max_size")
        self.assertEqual(self.action(invite).status_code, 200)
        self.assertEqual(self.solution.members.count(), 2)

    def test_accept_rechecks_membership_and_exclusivity(self):
        invite = self.invite()
        PartnerProgramUserProfile.objects.filter(
            user=self.recipient, partner_program=self.program
        ).delete()
        self.assert_error(self.action(invite), 409, "not_program_member")
        create_program_member(self.program, user=self.recipient)
        other = self.team()
        ProgramSolutionMember.objects.create(solution=other, user=self.recipient)
        self.assert_error(self.action(invite), 409, "already_in_program_team")
        self.assertEqual(SolutionInvitation.objects.get().status, "pending")

    def test_repeated_accept_decline_patch_and_revoke_do_not_change_history(self):
        invite = self.invite()
        accepted = self.action(invite)
        for response in [
            self.action(invite),
            self.action(invite, decision="decline"),
            call(
                self.captain,
                "delete",
                f"/solution-invitations/{invite['id']}/?expected_version=2&expected_solution_version=3",
            ),
            call(
                self.captain,
                "patch",
                f"/solution-invitations/{invite['id']}/",
                {"expected_version": 2, "expected_solution_version": 3, "role": "X"},
            ),
        ]:
            self.assert_error(response, 409, "invite_already_processed")
        self.assertEqual(self.solution.members.filter(user=self.recipient).count(), 1)
        self.assertEqual(
            SolutionInvitation.objects.get().version,
            accepted.data["invitation"]["version"],
        )

    def test_decline_and_revoke_after_submit_preserve_snapshot_and_change_service_versions(
        self,
    ):
        first = self.invite()
        second = self.invite(self.registered())
        snapshot = {
            "name": "Сданное решение",
            "captain_id": self.captain.pk,
            "members": [],
            "form": {},
            "answers": [],
        }
        ProgramSolution.objects.filter(pk=self.solution.pk).update(
            status="submitted", submitted_at=timezone.now(), submission_snapshot=snapshot
        )
        self.assert_error(self.action(first), 409, "team_frozen")
        self.assert_error(
            call(
                self.captain,
                "patch",
                f"/solution-invitations/{first['id']}/",
                {"expected_version": 1, "expected_solution_version": 3, "role": "X"},
            ),
            409,
            "team_frozen",
        )
        self.assert_error(self.create(self.registered()), 409, "team_frozen")
        declined = self.action(first, decision="decline")
        self.assertEqual(declined.status_code, 200, declined.data)
        self.validate_schema(declined, "InvitationActionResult")
        self.assertIsNone(declined.data["solution_version"])
        self.assertIsNone(declined.data["application"])
        revoked = call(
            self.captain,
            "delete",
            f"/solution-invitations/{second['id']}/?expected_version=1&expected_solution_version=4",
        )
        self.assertEqual(revoked.status_code, 204)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, 5)
        self.assertEqual(self.solution.submission_snapshot, snapshot)
        self.assertEqual(self.solution.status, "submitted")

    def test_mode_rollback_keeps_read_but_blocks_mutations(self):
        invite = self.invite()
        self.program.solution_storage_mode = "legacy_project"
        self.program.save()
        detail = call(self.recipient, "get", f"/solution-invitations/{invite['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(any(detail.data["permissions"].values()))
        self.assert_error(self.action(invite), 409, "solution_mode_unavailable")
        self.assert_error(
            self.action(invite, decision="decline"), 409, "solution_mode_unavailable"
        )

    def test_captain_transfer_updates_invitation_ownership_without_exposing_it_to_old_captain(
        self,
    ):
        invite = self.invite()
        new = self.member()
        solution_team.transfer_captain(
            program_id=self.program.pk,
            solution_id=self.solution.pk,
            user_id=new.pk,
            actor=self.captain,
            expected_version=2,
        )
        url = f"/solution-invitations/{invite['id']}/"
        self.assert_error(call(self.captain, "get", url), 404, "not_found")
        self.assertEqual(call(new, "get", url).data["captain"]["id"], new.pk)
        self.assertEqual(self.action(invite).status_code, 200)

    def test_strict_fields_types_lengths_and_identifiers(self):
        for fields in [
            {"project_id": 1},
            {"solution_id": 1},
            {"role": True},
            {"role": "x" * 129},
            {"specialization": "x" * 101},
            {"motivational_letter": "x" * 4097},
            {"recipient_user_id": True},
        ]:
            data = {
                "expected_solution_version": 1,
                "recipient_user_id": self.recipient.pk,
                **fields,
            }
            self.assert_error(
                call(self.captain, "post", self.root, data), 400, "validation_error"
            )
        invite = self.invite()
        self.assert_error(
            call(
                self.captain,
                "patch",
                f"/solution-invitations/{invite['id']}/",
                {"expected_version": 1, "expected_solution_version": 2},
            ),
            400,
            "validation_error",
        )
        self.assert_error(
            call(self.recipient, "get", "/solution-invitations/9007199254740992/"),
            404,
            "not_found",
        )
        self.assert_error(
            call(self.captain, "get", self.root + "?status=revoked"),
            400,
            "validation_error",
        )

    def test_pending_in_other_team_is_not_accepted_membership_and_finished_exceptions_hold(
        self,
    ):
        invite = self.invite()
        other = self.team()
        other_invitation = solution_invitations.create_invitation(
            program_id=self.program.pk,
            solution_id=other.pk,
            actor=other.captain,
            expected_solution_version=1,
            recipient_user_id=self.recipient.pk,
        )
        self.assertEqual(self.action(invite).status_code, 200)
        self.program.datetime_finished = timezone.now() - timezone.timedelta(days=1)
        self.program.save()
        self.assertEqual(
            self.action({"id": other_invitation.pk, "version": 1}).status_code, 200
        )


@skipUnlessDBFeature("has_select_for_update")
class SolutionInvitationConcurrencyTests(InvitationFixture, TransactionTestCase):
    def setUp(self):
        self.seed()

    def parallel(self, functions):
        barrier = Barrier(len(functions))

        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                function()
                return "success"
            except SolutionError as error:
                return str(error.get_codes())
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return list(pool.map(run, functions))

    def test_two_creates_of_same_version_have_one_pending_and_one_version_increment(self):
        def create():
            solution_invitations.create_invitation(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=self.captain,
                expected_solution_version=1,
                recipient_user_id=self.recipient.pk,
            )

        results = self.parallel([create, create])
        self.assertCountEqual(results, ["success", "version_conflict"])
        self.assertEqual(SolutionInvitation.objects.count(), 1)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, 2)

    def test_acceptance_of_two_solution_invitations_only_joins_one_team(self):
        first = self.invite()
        other = self.team()
        second = solution_invitations.create_invitation(
            program_id=self.program.pk,
            solution_id=other.pk,
            actor=other.captain,
            expected_solution_version=1,
            recipient_user_id=self.recipient.pk,
        )

        def accept(pk):
            solution_invitations.decide_invitation(
                invitation_id=pk, actor=self.recipient, expected_version=1, accept=True
            )

        results = self.parallel([lambda: accept(first["id"]), lambda: accept(second.pk)])
        self.assertCountEqual(results, ["success", "already_in_program_team"])
        self.assertEqual(
            ProgramSolutionMember.objects.filter(user=self.recipient).count(), 1
        )
