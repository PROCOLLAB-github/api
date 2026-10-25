import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Barrier
from time import monotonic, sleep, time
from unittest.mock import patch

from django.core import signing
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from jsonschema import Draft202012Validator

from partner_programs import solution_answers
from partner_programs.models import PartnerProgram, PartnerProgramField
from partner_programs.services import solution_case_actions as actions
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_submission import submit_solution
from partner_programs.solution_models import ProgramSolution
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_submission import SubmissionFixture
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.tests.helpers import create_rate_criteria, create_rate_expert
from projects.models import Project

FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class CaseFixture(SubmissionFixture):
    def setUp(self):
        self.ready()
        self.root = (
            f"/programs/{self.program.pk}/management/solutions/{self.solution.pk}/case/"
        )
        self.target = "Задача 2"
        PartnerProgramField.objects.filter(pk=self.fields["select"]["id"]).update(
            solution_options=["Задача 1", self.target], options="Задача 1|" + self.target
        )

    def preview(self, actor=None, case=None):
        return call(
            actor or self.manager,
            "post",
            self.root + "preview/",
            {"case_name": case or self.target},
        )

    def command_case(self):
        result = self.preview()
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data["can_apply"], result.data)
        return dict(case_name=self.target, preview_token=result.data["preview_token"])

    def apply(self, command, actor=None):
        return call(actor or self.manager, "post", self.root + "apply/", command)

    def saved(self):
        self.solution.refresh_from_db()
        return dict(
            solution=list(ProgramSolution.objects.filter(pk=self.solution.pk).values()),
            answers=list(self.solution.answers.order_by("pk").values()),
            members=list(self.solution.members.order_by("pk").values()),
            assignments=list(self.solution.expert_assignments.order_by("pk").values()),
            scores=list(self.solution.scores.order_by("pk").values()),
            projects=Project.objects.count(),
        )

    def wire(self, response, status=200, schema="SolutionCaseChangePreview"):
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
            }
        ).validate(response.data)
        return response.data


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionCaseActionTests(CaseFixture, TestCase):
    def test_preview_is_read_only_and_has_real_ref_case_field_and_version(self):
        before = self.saved()
        result = self.wire(self.preview())
        self.assertEqual(
            result["application"],
            dict(
                kind="solution",
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                name=self.solution.name,
            ),
        )
        self.assertEqual(result["case_field_id"], self.fields["select"]["id"])
        self.assertEqual(result["current_case"], "Задача 1")
        self.assertEqual(result["case_name"], "Задача 2")
        self.assertEqual(result["solution_version"], self.solution.version)
        self.assertEqual(result["errors"], [])
        proof = signing.loads(result["preview_token"], salt=actions.SALT)
        self.assertEqual(set(proof), {"actor", "program", "solution", "case", "state"})
        self.assertEqual(proof["solution"], self.solution.pk)
        self.assertEqual(proof["program"], self.program.pk)
        self.assertEqual(proof["actor"], self.manager.pk)
        self.assertEqual(proof["case"], self.target)
        self.assertEqual(self.saved(), before)

    def test_apply_changes_only_case_and_version_time_without_touching_zero_false_or_team(
        self,
    ):
        command = self.command_case()
        before = self.saved()
        result = self.wire(self.apply(command), schema="MutationReceipt")
        after = self.saved()
        self.assertEqual(result["solution_id"], self.solution.pk)
        self.assertEqual(result["solution_version"], before["solution"][0]["version"] + 1)
        self.assertEqual(after["members"], before["members"])
        self.assertEqual(after["projects"], before["projects"])
        self.assertEqual(after["assignments"], [])
        for key, value in before["solution"][0].items():
            if key not in ("version", "updated_at"):
                self.assertEqual(after["solution"][0][key], value)
        for row in before["answers"]:
            expected = (
                {**row, "value": self.target}
                if row["field_id"] == self.fields["select"]["id"]
                else row
            )
            self.assertIn(expected, after["answers"])
        values = {a["field_id"]: a["value"] for a in after["answers"]}
        self.assertEqual(values[self.fields["number"]["id"]], 0)
        self.assertIs(values[self.fields["checkbox"]["id"]], False)

    def test_missing_case_and_exact_spaces_pipe_choice_are_supported(self):
        self.solution.answers.filter(field_id=self.fields["select"]["id"]).delete()
        target = "  Город | Образование  "
        PartnerProgramField.objects.filter(pk=self.fields["select"]["id"]).update(
            solution_options=["Задача 1", self.target, target]
        )
        response = self.wire(self.preview(case=target))
        self.assertIsNone(response["current_case"])
        self.wire(
            self.apply(dict(case_name=target, preview_token=response["preview_token"])),
            schema="MutationReceipt",
        )
        self.assertEqual(
            self.solution.answers.get(field_id=self.fields["select"]["id"]).value, target
        )

    def test_same_case_has_no_confirmation_and_no_write(self):
        before = self.saved()
        response = self.wire(self.preview(case="Задача 1"))
        self.assertFalse(response["can_apply"])
        self.assertIsNone(response["preview_token"])
        self.assertEqual(response["errors"][0]["code"], "case_unchanged")
        self.assertEqual(self.saved(), before)

    def test_manager_staff_scoping_and_foreign_solution_ids(self):
        member = create_user()
        create_program_member(self.program, user=member)
        expert = create_rate_expert()
        expert.expert.programs.add(self.program)
        other_program = create_partner_program(solution_storage_mode="solution")
        foreign = create_user()
        other_program.managers.add(foreign)
        for actor in (self.captain, member, expert, foreign):
            with self.subTest(actor=actor.pk):
                self.assertEqual(
                    self.wire(self.preview(actor=actor), 403)["code"], "permission_denied"
                )
        self.wire(self.preview(actor=create_user(is_staff=True)))
        obj = ProgramSolution.objects.create(program=other_program, captain=foreign)
        response = call(
            self.manager,
            "post",
            f"/programs/{self.program.pk}/management/solutions/{obj.pk}/case/preview/",
            {"case_name": self.target},
        )
        self.assertEqual(self.wire(response, 404)["code"], "not_found")
        self.assertEqual(
            self.wire(
                call(None, "post", self.root + "preview/", {"case_name": self.target}),
                401,
            )["code"],
            "authentication_required",
        )

    def test_strict_case_and_unknown_input_query_safe_ids(self):
        before = self.saved()
        for data in (
            {},
            {"case_name": ""},
            {"case_name": "   "},
            {"case_name": 12},
            {"case_name": True},
            {"case_name": []},
            {"case_name": "a" * 1001},
            {"case_name": self.target, "ids": [self.solution.pk]},
            {"case_name": self.target, "action": "change_case"},
        ):
            with self.subTest(data=data):
                self.wire(call(self.manager, "post", self.root + "preview/", data), 400)
        self.wire(
            call(
                self.manager,
                "post",
                self.root + "preview/?unknown=1",
                {"case_name": self.target},
            ),
            400,
        )
        for value in (0, 9007199254740992):
            self.wire(
                call(
                    self.manager,
                    "post",
                    f"/programs/{self.program.pk}/management/solutions/{value}/case/preview/",
                    {"case_name": self.target},
                ),
                404,
            )
        self.assertEqual(self.saved(), before)

    def test_invalid_option_returns_field_issue_and_does_not_write(self):
        before = self.saved()
        error = self.wire(self.preview(case="Неизвестный кейс"), 400)
        self.assertEqual(error["code"], "invalid_answers")
        self.assertEqual(error["errors"][0]["field_id"], self.fields["select"]["id"])
        self.assertEqual(self.saved(), before)

    def test_confirmation_requires_a_string_token_before_any_write(self):
        before = self.saved()
        for token in (0, True, [], {}, None, "", "x" * 200001):
            with self.subTest(token_type=type(token).__name__):
                result = self.wire(
                    self.apply(dict(case_name=self.target, preview_token=token)), 400
                )
                self.assertEqual(result["code"], "validation_error")
        self.assertEqual(self.saved(), before)

    def test_noncompetitive_deadline_and_creation_switch_do_not_disable_existing_case(
        self,
    ):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            is_competitive=False,
            solution_creation_enabled=False,
            datetime_project_submission_ends=timezone.now() - timezone.timedelta(days=1),
        )
        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.status, "draft")
        self.assertIsNone(self.solution.submission_snapshot)

    def test_submitted_preview_and_apply_preserve_snapshot_and_scores(self):
        command = self.command_case()
        self.assertEqual(self.submit().status_code, 200)
        expert = create_rate_expert(program=self.program)
        criterion = create_rate_criteria(self.program, min_value=0, max_value=10)
        SolutionExpertAssignment.objects.create(
            partner_program=self.program, solution=self.solution, expert=expert.expert
        )
        SolutionScore.objects.create(
            solution=self.solution, criteria=criterion, user=expert, value="0"
        )
        before = self.saved()
        response = self.wire(self.preview())
        self.assertFalse(response["can_apply"])
        self.assertIsNone(response["preview_token"])
        self.assertEqual(response["errors"][0]["code"], "team_frozen")
        self.assertEqual(self.wire(self.apply(command), 409)["code"], "team_frozen")
        self.assertEqual(self.saved(), before)

    def test_unexpected_draft_score_is_not_removed(self):
        expert = create_rate_expert(program=self.program)
        criterion = create_rate_criteria(self.program, min_value=0, max_value=10)
        SolutionScore.objects.bulk_create(
            [
                SolutionScore(
                    solution=self.solution, criteria=criterion, user=expert, value="0"
                )
            ]
        )
        before = self.saved()
        result = self.wire(self.preview())
        self.assertFalse(result["can_apply"])
        self.assertIsNone(result["preview_token"])
        self.assertEqual(result["errors"][0]["code"], "evaluation_started")
        self.assertEqual(self.saved(), before)

    def test_unexpected_draft_assignment_is_not_removed(self):
        expert = create_rate_expert()
        SolutionExpertAssignment.objects.bulk_create(
            [
                SolutionExpertAssignment(
                    partner_program=self.program,
                    solution=self.solution,
                    expert=expert.expert,
                )
            ]
        )
        before = self.saved()
        result = self.wire(self.preview())
        self.assertFalse(result["can_apply"])
        self.assertIsNone(result["preview_token"])
        self.assertEqual(result["errors"][0]["code"], "evaluation_started")
        self.assertEqual(self.saved(), before)

    def test_replay_bad_signature_payload_and_expiry_do_not_write(self):
        command = self.command_case()
        before = self.saved()
        for token in (
            "not-a-token",
            signing.dumps([], salt=actions.SALT),
            signing.dumps({}, salt="solution-submission-actions-v1"),
        ):
            self.assertEqual(
                self.wire(self.apply({**command, "preview_token": token}), 409)["code"],
                "solution_action_conflict",
            )
        with patch("django.core.signing.time.time", return_value=time() - 601):
            expired = self.command_case()
        self.assertEqual(
            self.wire(self.apply(expired), 409)["code"], "solution_action_conflict"
        )
        self.assertEqual(self.saved(), before)
        self.wire(self.apply(command), schema="MutationReceipt")
        after = self.saved()
        self.wire(self.apply(command), 409)
        self.assertEqual(self.saved(), after)

    def test_actor_target_and_program_binding_cannot_be_reused(self):
        command = self.command_case()
        staff = create_user(is_staff=True)
        self.wire(self.apply(command, actor=staff), 409)
        self.wire(self.apply({**command, "case_name": "Задача 1"}), 409)
        other = ProgramSolution.objects.create(
            program=self.program, captain=create_user()
        )
        self.wire(
            call(
                self.manager,
                "post",
                f"/programs/{self.program.pk}/management/solutions/{other.pk}/case/apply/",
                command,
            ),
            409,
        )

    def test_admin_changes_without_solution_version_bump_invalidate_proof(self):
        changes = [
            lambda: self.solution.answers.filter(
                field_id=self.fields["number"]["id"]
            ).update(value=5),
            lambda: self.solution.members.update(role="Другая роль"),
            lambda: PartnerProgramField.objects.filter(
                pk=self.fields["select"]["id"]
            ).update(label="Новая подпись"),
            lambda: ProgramSolution.objects.filter(pk=self.solution.pk).update(
                name="Другое название"
            ),
        ]
        for change in changes:
            with self.subTest(change=change), transaction.atomic():
                command = self.command_case()
                change()
                changed = self.saved()
                self.assertEqual(
                    self.wire(self.apply(command), 409)["code"],
                    "solution_action_conflict",
                )
                self.assertEqual(self.saved(), changed)
                transaction.set_rollback(True)

    def test_legacy_and_unconfigured_modes_are_explicit(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_storage_mode="legacy_project"
        )
        self.assertEqual(
            self.wire(self.preview(), 409)["code"], "solution_mode_unavailable"
        )
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_storage_mode="solution", solution_template=None
        )
        self.assertEqual(self.wire(self.preview(), 409)["code"], "form_not_configured")


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionCaseActionConcurrencyTests(CaseFixture, TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL program locks")
        super().setUp()

    def race(self, commands):
        barrier, pids = Barrier(2), Queue()

        def run(command):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.put(cursor.fetchone()[0])
                barrier.wait(timeout=10)
                try:
                    command()
                    return "saved"
                except SolutionError as error:
                    return error.payload["code"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                PartnerProgram.objects.select_for_update().get(pk=self.program.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    controller = cursor.fetchone()[0]
                futures = [pool.submit(run, command) for command in commands]
                workers = [pids.get(timeout=10), pids.get(timeout=10)]
                until, paths = monotonic() + 10, []
                while monotonic() < until:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity WHERE datname=current_database()"
                        )
                        blockers = dict(cursor.fetchall())
                    paths = []
                    for pid in workers:
                        seen, queue = set(), [pid]
                        while queue:
                            current = queue.pop()
                            if current in seen:
                                continue
                            seen.add(current)
                            queue.extend(blockers.get(current, []))
                        paths.append(controller in seen)
                    if all(paths):
                        break
                    sleep(0.01)
                self.assertEqual(paths, [True, True])
            return [f.result(timeout=20) for f in futures]

    def test_two_confirmations_have_one_change(self):
        command = self.command_case()
        self.solution.refresh_from_db()
        before = self.solution.version

        def fn():
            return actions.apply(self.program.pk, self.solution.pk, self.manager, command)

        self.assertCountEqual(self.race([fn, fn]), ["saved", "solution_action_conflict"])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, before + 1)
        self.assertEqual(
            self.solution.answers.get(field_id=self.fields["select"]["id"]).value,
            self.target,
        )

    def test_confirmation_and_captain_patch_keep_one_ordered_version(self):
        command = self.command_case()
        patch_command = self.command(name="Локальная правка")
        before = self.solution.version

        def fn():
            return actions.apply(self.program.pk, self.solution.pk, self.manager, command)

        def update():
            return solution_answers.update_solution(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=self.captain,
                **patch_command,
            )

        result = self.race([fn, update])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, before + 1)
        if result[0] == "saved":
            self.assertEqual(result, ["saved", "version_conflict"])
            self.assertNotEqual(self.solution.name, "Локальная правка")
            self.assertEqual(
                self.solution.answers.get(field_id=self.fields["select"]["id"]).value,
                self.target,
            )
        else:
            self.assertEqual(result, ["solution_action_conflict", "saved"])
            self.assertEqual(self.solution.name, "Локальная правка")
            self.assertEqual(
                self.solution.answers.get(field_id=self.fields["select"]["id"]).value,
                "Задача 1",
            )

    def test_confirmation_and_submission_never_change_a_frozen_snapshot(self):
        command = self.command_case()
        submission = self.command()
        before = self.solution.version

        def change():
            return actions.apply(self.program.pk, self.solution.pk, self.manager, command)

        def submit():
            return submit_solution(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=self.captain,
                **submission,
            )

        result = self.race([change, submit])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, before + 1)
        if result[0] == "saved":
            self.assertEqual(result, ["saved", "version_conflict"])
            self.assertEqual(self.solution.status, "draft")
            self.assertIsNone(self.solution.submission_snapshot)
            self.assertEqual(
                self.solution.answers.get(field_id=self.fields["select"]["id"]).value,
                self.target,
            )
        else:
            self.assertEqual(result, ["team_frozen", "saved"])
            self.assertEqual(self.solution.status, "submitted")
            answers = {
                a["field_id"]: a["value"]
                for a in self.solution.submission_snapshot["answers"]
            }
            self.assertEqual(answers[self.fields["select"]["id"]], "Задача 1")
            self.assertEqual(
                self.solution.answers.get(field_id=self.fields["select"]["id"]).value,
                "Задача 1",
            )
