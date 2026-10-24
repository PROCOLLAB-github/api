import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections, transaction
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from partner_programs import (
    solution_answers,
    solution_invitations,
    solution_forms,
    solution_team,
)
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_models import (
    ProgramSolutionMember,
    ProgramSolutionAnswer,
    SolutionInvitation,
)
from partner_programs.solution_submission import submit_solution
from partner_programs.tests.test_solution_answers import AnswerFixture
from partner_programs.tests.test_solution_forms import call, new_field
from partner_programs.tests.helpers import create_user, create_program_member


class SubmissionFixture(AnswerFixture):
    def ready(self):
        self.seed_answers()
        self.program.legacy_team_min_size = 1
        self.program.legacy_team_max_size = 4
        self.program.save()
        rows = [
            {"field_id": self.fields["select"]["id"], "value": "Задача 1"},
            {"field_id": self.fields["textarea"]["id"], "value": "Готовое решение"},
            {"field_id": self.fields["number"]["id"], "value": 0},
            {"field_id": self.fields["checkbox"]["id"], "value": False},
        ]
        response = self.save_answers(rows)
        assert response.status_code == 200, response.data
        self.submit_url = self.url + "submit/"

    def submit(self, **changes):
        return call(self.captain, "post", self.submit_url, self.command(**changes))


class SolutionSubmissionTests(SubmissionFixture, TestCase):
    def setUp(self):
        self.ready()

    def assert_draft(self):
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.status, "draft")
        self.assertIsNone(self.solution.submitted_at)
        self.assertIsNone(self.solution.submission_snapshot)

    def test_submit_matches_contract_and_snapshots_exact_values_and_accepted_team(self):
        recipient = create_user()
        SolutionInvitation.objects.create(
            solution=self.solution, recipient=recipient, role="Дизайнер"
        )
        before = self.command()["expected_version"]
        response = self.submit()
        self.assertEqual(response.status_code, 200, response.data)
        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        from jsonschema import Draft202012Validator, FormatChecker

        Draft202012Validator(
            {"components": spec["components"], "$ref": "#/components/schemas/Solution"},
            format_checker=FormatChecker(),
        ).validate(response.data)
        self.assertEqual(response.data["version"], before + 1)
        self.assertEqual(response.data["submission"]["status"], "submitted")
        self.assertTrue(response.data["form"]["is_snapshot"])
        self.assertTrue(response.data["readiness"]["is_ready"])
        self.assertEqual(response.data["team"]["accepted_count"], 1)
        self.assertEqual(response.data["team"]["pending_count"], 1)
        self.assertFalse(response.data["permissions"]["can_edit"])
        self.assertFalse(response.data["permissions"]["can_submit"])
        self.solution.refresh_from_db()
        self.assertEqual(
            self.solution.submission_snapshot["answers"], response.data["answers"]
        )
        self.assertEqual(
            self.solution.submission_snapshot["members"], response.data["team"]["members"]
        )
        self.assertEqual(
            self.solution.submission_snapshot["submitted_at"],
            response.data["submission"]["submitted_at"],
        )
        self.assertIn(False, [row["value"] for row in response.data["answers"]])
        self.assertIn(0, [row["value"] for row in response.data["answers"]])

    def test_incomplete_case_and_invalid_choice_are_controlled_and_atomic(self):
        self.save_answers([{"field_id": self.fields["select"]["id"], "value": None}])
        response = self.submit()
        self.assert_error(response, "case_required", 400)
        self.assertEqual(
            response.data["errors"][0]["field_id"], self.fields["select"]["id"]
        )
        self.assert_draft()
        ProgramSolutionAnswer.objects.create(
            solution=self.solution,
            field_id=self.fields["select"]["id"],
            value="Устаревший кейс",
        )
        self.assert_error(self.submit(), "case_unavailable", 400)
        self.assert_draft()

    def test_required_and_constraints_are_rechecked_even_for_old_data(self):
        self.save_answers([{"field_id": self.fields["textarea"]["id"], "value": None}])
        response = self.submit()
        self.assert_error(response, "required_program_fields", 400)
        self.assert_draft()
        ProgramSolutionAnswer.objects.create(
            solution=self.solution, field_id=self.fields["textarea"]["id"], value=True
        )
        self.assert_error(self.submit(), "invalid_answers", 400)
        self.assert_draft()

    def test_only_captain_can_submit_visible_solution(self):
        member = create_user()
        create_program_member(self.program, user=member)
        ProgramSolutionMember.objects.create(solution=self.solution, user=member)
        for actor in (member, self.manager):
            self.assert_error(
                call(actor, "post", self.submit_url, self.command()),
                "not_solution_captain",
                403,
            )
        self.assert_error(
            call(create_user(), "post", self.submit_url, self.command()), "not_found", 404
        )
        self.assert_draft()

    def test_minimum_counts_accepted_only_and_deadline_precedes_team_and_fields(self):
        self.program.legacy_team_min_size = 2
        self.program.save()
        pending = create_user()
        SolutionInvitation.objects.create(solution=self.solution, recipient=pending)
        self.assert_error(self.submit(), "team_min_size")
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(seconds=1)
        )
        self.program.save()
        self.assert_error(self.submit(), "submission_closed")
        self.assert_draft()
        self.assertFalse(
            call(self.captain, "get", self.url).data["permissions"]["can_submit"]
        )

    def test_inclusive_deadline_uses_existing_program_clock(self):
        stamp = timezone.now()
        self.program.datetime_project_submission_ends = stamp
        self.program.save()
        with patch("partner_programs.models.timezone.now", return_value=stamp):
            response = self.submit()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["submission"]["submitted_at"],
            stamp.isoformat().replace("+00:00", "Z"),
        )

    def test_versions_mode_and_noncompetitive_block_without_mutating_saved_draft(self):
        body = self.command()
        body["expected_version"] = 999
        self.assert_error(
            call(self.captain, "post", self.submit_url, body), "version_conflict"
        )
        body = self.command()
        body["expected_form_revision"] = "b" * 64
        self.assert_error(
            call(self.captain, "post", self.submit_url, body), "form_revision_conflict"
        )
        self.program.is_competitive = False
        self.program.save()
        self.assert_error(self.submit(), "not_competitive")
        data = call(self.captain, "get", self.url).data
        self.assertIsNone(data["readiness"])
        self.assertFalse(data["submission"]["required"])
        self.assertEqual(self.save_answers([], name="Работа без сдачи").status_code, 200)
        self.program.solution_storage_mode = "legacy_project"
        self.program.save()
        self.assert_error(self.submit(), "solution_mode_unavailable")
        self.assert_draft()

    def test_repeated_submit_checks_final_state_before_stale_versions_and_new_deadline(
        self,
    ):
        body = self.command()
        self.assertEqual(self.submit().status_code, 200)
        self.solution.refresh_from_db()
        snapshot = copy.deepcopy(self.solution.submission_snapshot)
        version = self.solution.version
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(seconds=1)
        )
        self.program.save()
        self.assert_error(
            call(self.captain, "post", self.submit_url, body), "already_submitted"
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, version)
        self.assertEqual(self.solution.submission_snapshot, snapshot)

    def test_snapshot_survives_form_labels_order_and_new_required_field(self):
        submitted = self.submit().data
        payload = self.payload()
        payload["fields"].reverse()
        for position, field in enumerate(payload["fields"]):
            field["position"] = position
            field["label"] = "Новое " + field["label"]
        payload["fields"].append(new_field(position=20, required=True))
        solution_forms.save_form(
            program_id=self.program.pk, actor=self.manager, **payload
        )
        self.program.legacy_team_min_size = 3
        self.program.save()
        current = call(self.captain, "get", self.url).data
        self.assertEqual(current["form"], submitted["form"])
        self.assertEqual(current["answers"], submitted["answers"])
        self.assertTrue(current["readiness"]["is_ready"])

    def test_file_disappearing_or_changing_before_submit_is_rejected(self):
        upload = self.upload()
        self.save_answers(
            [{"field_id": self.fields["file"]["id"], "value": {"url": upload.link}}]
        )
        upload.detected_mime_type = "application/zip"
        upload.save()
        response = self.submit()
        self.assert_error(response, "invalid_answers", 400)
        self.assertEqual(response.data["errors"][0]["code"], "file_type_mismatch")
        self.assert_draft()
        upload.delete()
        self.assert_error(self.submit(), "invalid_answers", 400)
        self.assert_draft()

    def test_optional_file_with_invalid_legacy_shape_is_controlled(self):
        ProgramSolutionAnswer.objects.create(
            solution=self.solution, field_id=self.fields["file"]["id"], value=""
        )
        self.assert_error(self.submit(), "invalid_answers", 400)
        self.assert_draft()

    def test_submit_failure_rolls_back_transition_but_keeps_previous_patch(self):
        with patch(
            "partner_programs.solution_submission.advance_version",
            side_effect=RuntimeError("commit failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assert_draft()
        self.assertEqual(self.solution.answers.count(), 4)

    def test_submitted_rejects_answer_and_team_commands_but_pending_revoke_works(self):
        recipient = create_user()
        create_program_member(self.program, user=recipient)
        invitation = solution_invitations.create_invitation(
            program_id=self.program.pk,
            solution_id=self.solution.pk,
            actor=self.captain,
            expected_solution_version=self.command()["expected_version"],
            recipient_user_id=recipient.pk,
            role="Разработчик",
        )
        self.assertEqual(self.submit().status_code, 200)
        self.solution.refresh_from_db()
        snapshot = copy.deepcopy(self.solution.submission_snapshot)
        self.assert_error(self.save_answers([], name="После сдачи"), "team_frozen")
        with self.assertRaises(SolutionError) as error:
            solution_invitations.decide_invitation(
                invitation_id=invitation.pk,
                actor=recipient,
                expected_version=invitation.version,
                accept=True,
            )
        self.assertEqual(error.exception.payload["code"], "team_frozen")
        solution_invitations.revoke_invitation(
            invitation_id=invitation.pk,
            actor=self.captain,
            expected_version=invitation.version,
            expected_solution_version=self.solution.version,
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.submission_snapshot, snapshot)

    def test_supported_model_writes_and_bulk_deletion_cannot_change_frozen_work(self):
        self.assertEqual(self.submit().status_code, 200)
        self.solution.refresh_from_db()
        snapshot = copy.deepcopy(self.solution.submission_snapshot)
        self.solution.name = "Подмена"
        with self.assertRaises(ValidationError), transaction.atomic():
            self.solution.save()
        self.solution.refresh_from_db()
        self.solution.status = "draft"
        self.solution.submitted_at = None
        self.solution.submission_snapshot = None
        with self.assertRaises(ValidationError), transaction.atomic():
            self.solution.save()
        answer = self.solution.answers.first()
        answer.value = "Подмена"
        with self.assertRaises(ValidationError), transaction.atomic():
            answer.save()
        with self.assertRaises(ValidationError), transaction.atomic():
            ProgramSolutionMember.objects.create(
                solution=self.solution, user=create_user()
            )
        with self.assertRaises(ValidationError), transaction.atomic():
            SolutionInvitation.objects.create(
                solution=self.solution, recipient=create_user()
            )
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.solution.members.all().delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.solution.answers.all().delete()
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.submission_snapshot, snapshot)
        self.assertEqual(self.solution.status, "submitted")


class SolutionSubmissionConcurrencyTests(SubmissionFixture, TransactionTestCase):
    def race(self, actions):
        barrier = Barrier(2)

        def run(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                action()
                return "saved"
            except SolutionError as error:
                return error.payload["code"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, actions))

    def submit_action(self):
        command = self.command()
        return lambda: submit_solution(
            program_id=self.program.pk,
            solution_id=self.solution.pk,
            actor=self.captain,
            **command
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_submits_make_exactly_one_snapshot(self):
        self.ready()
        action = self.submit_action()
        self.assertCountEqual(self.race([action, action]), ["saved", "already_submitted"])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.status, "submitted")

    @skipUnlessDBFeature("has_select_for_update")
    def test_submit_and_patch_serialize_without_changing_snapshot(self):
        self.ready()
        submit = self.submit_action()
        command = self.command(name="Одновременная правка")

        def update():
            solution_answers.update_solution(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=self.captain,
                **command
            )

        results = self.race([submit, update])
        self.solution.refresh_from_db()
        if self.solution.status == "submitted":
            self.assertEqual(results, ["saved", "team_frozen"])
            self.assertNotEqual(
                self.solution.submission_snapshot["name"], "Одновременная правка"
            )
        else:
            self.assertEqual(results, ["version_conflict", "saved"])
            self.assertEqual(self.solution.name, "Одновременная правка")
            self.assertIsNone(self.solution.submission_snapshot)

    @skipUnlessDBFeature("has_select_for_update")
    def test_submit_and_remove_keep_one_accepted_roster(self):
        self.ready()
        member = create_user()
        create_program_member(self.program, user=member)
        ProgramSolutionMember.objects.create(solution=self.solution, user=member)
        submit = self.submit_action()
        version = self.solution.version

        def remove():
            solution_team.remove_member(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=self.captain,
                user_id=member.pk,
                expected_version=version,
            )

        results = self.race([submit, remove])
        self.solution.refresh_from_db()
        if self.solution.status == "submitted":
            self.assertEqual(results, ["saved", "team_frozen"])
            self.assertEqual(len(self.solution.submission_snapshot["members"]), 2)
        else:
            self.assertEqual(results, ["version_conflict", "saved"])
            self.assertEqual(self.solution.members.count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_submit_and_accept_never_add_a_member_to_the_frozen_roster(self):
        self.ready()
        recipient = create_user()
        create_program_member(self.program, user=recipient)
        invitation = solution_invitations.create_invitation(
            program_id=self.program.pk,
            solution_id=self.solution.pk,
            actor=self.captain,
            expected_solution_version=self.command()["expected_version"],
            recipient_user_id=recipient.pk,
            role="Аналитик",
        )
        submit = self.submit_action()

        def accept():
            solution_invitations.decide_invitation(
                invitation_id=invitation.pk,
                actor=recipient,
                expected_version=invitation.version,
                accept=True,
            )

        results = self.race([submit, accept])
        self.solution.refresh_from_db()
        if self.solution.status == "submitted":
            self.assertEqual(results, ["saved", "team_frozen"])
            self.assertEqual(len(self.solution.submission_snapshot["members"]), 1)
            self.assertEqual(self.solution.members.count(), 1)
        else:
            self.assertEqual(results, ["version_conflict", "saved"])
            self.assertEqual(self.solution.members.count(), 2)

    @skipUnlessDBFeature("has_select_for_update")
    def test_submit_and_form_change_either_conflict_or_keep_the_old_snapshot(self):
        self.ready()
        submit = self.submit_action()
        payload = self.payload()
        old_revision = payload["expected_revision"]
        payload["fields"].append(new_field(position=20, required=True))

        def configure():
            solution_forms.save_form(
                program_id=self.program.pk, actor=self.manager, **payload
            )

        results = self.race([submit, configure])
        self.solution.refresh_from_db()
        if self.solution.status == "submitted":
            self.assertEqual(results, ["saved", "saved"])
            self.assertEqual(
                self.solution.submission_snapshot["form"]["revision"], old_revision
            )
        else:
            self.assertEqual(results, ["form_revision_conflict", "saved"])
            self.assertIsNone(self.solution.submission_snapshot)

    @skipUnlessDBFeature("has_select_for_update")
    def test_file_delete_and_submit_share_the_file_lock(self):
        from files.views import FileView
        from files.models import UserFile
        from rest_framework.test import APIClient

        self.ready()
        upload = self.upload()
        self.save_answers(
            [{"field_id": self.fields["file"]["id"], "value": {"url": upload.link}}]
        )
        submit = self.submit_action()

        def delete():
            client = APIClient()
            client.force_authenticate(self.captain)
            response = client.delete("/files/", QUERY_STRING="link=" + upload.link)
            if response.status_code != 204:
                raise SolutionError(response.data["code"], response.data["detail"])

        with patch.object(FileView.cdn, "delete"):
            results = self.race([submit, delete])
        self.solution.refresh_from_db()
        if self.solution.status == "submitted":
            self.assertEqual(results, ["saved", "file_in_use"])
            self.assertTrue(UserFile.objects.filter(pk=upload.pk).exists())
        else:
            self.assertEqual(results, ["invalid_answers", "saved"])
            self.assertFalse(UserFile.objects.filter(pk=upload.pk).exists())
