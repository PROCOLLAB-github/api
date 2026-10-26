import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Barrier
from time import monotonic, sleep

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from jsonschema import Draft202012Validator

from files.models import UserFile
from partner_programs.models import PartnerProgram, PartnerProgramField
from partner_programs.services import solution_submission_actions as actions
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs.tests.helpers import (
    create_user,
    create_program_member,
    create_partner_program,
)
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_submission import SubmissionFixture
from projects.models import Project
from project_rates.tests.helpers import create_rate_expert

FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class ActionFixture(SubmissionFixture):
    def setUp(self):
        self.ready()
        self.action_root = f"/programs/{self.program.pk}/management/solutions/actions/"

    def selection(self, ids=None, **extra):
        return dict(action="submit", ids=ids or [self.solution.pk], **extra)

    def preview(self, ids=None, actor=None):
        return call(
            actor or self.manager,
            "post",
            self.action_root + "preview/",
            self.selection(ids),
        )

    def confirmation(self, ids=None):
        response = self.preview(ids)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["can_apply"], response.data)
        return self.selection(ids, preview_token=response.data["preview_token"])

    def apply(self, data, actor=None):
        return call(actor or self.manager, "post", self.action_root + "apply/", data)

    def wire(self, response, status=200, schema="SolutionActionPreview"):
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

    def saved(self, solution=None):
        solution = solution or self.solution
        solution.refresh_from_db()
        return dict(
            version=solution.version,
            status=solution.status,
            submitted_at=solution.submitted_at,
            snapshot=copy.deepcopy(solution.submission_snapshot),
        )

    def another(self, *, incomplete=False):
        captain = create_user()
        create_program_member(self.program, user=captain)
        solution = ProgramSolution.objects.create(
            program=self.program, captain=captain, name="Второе решение"
        )
        ProgramSolutionMember.objects.create(solution=solution, user=captain)
        ProgramSolutionAnswer.objects.bulk_create(
            [
                ProgramSolutionAnswer(
                    solution=solution,
                    field_id=row.field_id,
                    value=copy.deepcopy(row.value),
                )
                for row in self.solution.answers.all()
                if not (incomplete and row.field_id == self.fields["textarea"]["id"])
            ]
        )
        return solution


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionSubmissionActionTests(ActionFixture, TestCase):
    def test_preview_is_read_only_uses_solution_refs_and_normalizes_duplicate_ids(self):
        before = self.saved()
        result = self.wire(self.preview([self.solution.pk, self.solution.pk]))
        self.assertEqual(result["ready_count"], 1)
        self.assertEqual(result["already_submitted_count"], 0)
        self.assertEqual(
            result["items"][0]["application"]["solution_id"], self.solution.pk
        )
        self.assertEqual(result["items"][0]["application"]["kind"], "solution")
        proof = signing.loads(result["preview_token"], salt=actions.SALT)
        self.assertEqual(proof["ids"], [self.solution.pk])
        self.assertEqual(set(proof), {"actor", "program", "action", "ids", "state"})
        self.assertEqual(self.saved(), before)

    def test_late_first_submission_keeps_captain_deadline_and_exact_snapshot(self):
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(days=1)
        )
        self.program.save()
        self.assert_error(self.submit(), "submission_closed")
        pending = create_user()
        SolutionInvitation.objects.create(
            solution=self.solution, recipient=pending, role="Дизайнер"
        )
        before_projects = Project.objects.count()
        before = self.saved()
        self.wire(self.apply(self.confirmation()), schema="SolutionActionResult")
        after = self.saved()
        self.assertEqual(after["version"], before["version"] + 1)
        self.assertEqual(after["status"], "submitted")
        snapshot = after["snapshot"]
        values = {a["field_id"]: a["value"] for a in snapshot["answers"]}
        self.assertEqual(values[self.fields["number"]["id"]], 0)
        self.assertIs(values[self.fields["checkbox"]["id"]], False)
        self.assertEqual(
            [m["user"]["id"] for m in snapshot["members"]], [self.captain.pk]
        )
        self.assertTrue(snapshot["form"]["is_snapshot"])
        self.assertEqual(Project.objects.count(), before_projects)
        self.assertEqual(self.solution.invitations.filter(status="pending").count(), 1)
        self.assert_error(self.save_answers(name="Поздняя правка"), "team_frozen")
        self.assertEqual(self.saved(), after)

    def test_all_already_submitted_cannot_apply_and_do_not_change_saved_state(self):
        self.assertEqual(self.submit().status_code, 200)
        before = self.saved()
        result = self.wire(self.preview())
        self.assertEqual(
            (result["ready_count"], result["already_submitted_count"]), (0, 1)
        )
        self.assertFalse(result["can_apply"])
        self.assertIsNone(result["preview_token"])
        self.assertEqual(self.saved(), before)

    def test_mixed_bulk_skips_submitted_and_preserves_its_date_and_snapshot(self):
        other = self.another()
        self.assertEqual(self.submit().status_code, 200)
        before = self.saved()
        result = self.wire(
            self.apply(self.confirmation([other.pk, self.solution.pk])),
            schema="SolutionActionResult",
        )
        self.assertEqual(result, {"changed_count": 1, "already_submitted_count": 1})
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.saved(other)["status"], "submitted")

    def test_incomplete_bulk_never_offers_token_or_changes_ready_neighbor(self):
        other = self.another(incomplete=True)
        before = self.saved()
        result = self.wire(self.preview([other.pk, self.solution.pk]))
        self.assertEqual(result["ready_count"], 1)
        self.assertFalse(result["can_apply"])
        self.assertIsNone(result["preview_token"])
        self.assertTrue(
            next(
                i for i in result["items"] if i["application"]["solution_id"] == other.pk
            )["errors"]
        )
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.saved(other)["status"], "draft")

    def test_roles_foreign_manager_and_anonymous_are_denied_on_both_operations(self):
        member = create_user()
        create_program_member(self.program, user=member)
        ProgramSolutionMember.objects.create(solution=self.solution, user=member)
        outsider = create_user()
        foreign_program = create_partner_program()
        foreign_program.managers.add(outsider)
        expert = create_rate_expert(program=self.program)
        for actor in [self.captain, member, outsider, expert, None]:
            for operation in ["preview", "apply"]:
                with self.subTest(actor=actor and actor.pk, operation=operation):
                    data = self.selection(
                        **({"preview_token": "invalid"} if operation == "apply" else {})
                    )
                    self.wire(
                        call(actor, "post", self.action_root + operation + "/", data),
                        401 if actor is None else 403,
                    )

    def test_staff_uses_existing_program_admin_right(self):
        staff = create_user(is_staff=True)
        self.wire(self.preview(actor=staff))

    def test_legacy_and_noncompetitive_modes_do_not_write(self):
        before = self.saved()
        for changes, code in [
            ({"solution_storage_mode": "legacy_project"}, "solution_mode_unavailable"),
            (
                {"solution_storage_mode": "solution", "is_competitive": False},
                "not_competitive",
            ),
        ]:
            PartnerProgram.objects.filter(pk=self.program.pk).update(**changes)
            for operation in ["preview", "apply"]:
                data = self.selection(
                    **({"preview_token": "invalid"} if operation == "apply" else {})
                )
                response = call(
                    self.manager, "post", self.action_root + operation + "/", data
                )
                self.assertEqual(self.wire(response, 409)["code"], code)
        self.assertEqual(self.saved(), before)

    def test_foreign_and_missing_solution_ids_do_not_disclose_or_submit(self):
        foreign = ProgramSolution.objects.create(
            program=create_partner_program(), captain=create_user()
        )
        for ids in [[foreign.pk], [self.solution.pk, foreign.pk], [9007199254740990]]:
            self.wire(self.preview(ids), 404)
        self.assertEqual(self.saved()["status"], "draft")

    def test_strict_body_query_safe_ids_and_only_submit_action(self):
        invalid = [
            dict(action="submit", ids=[]),
            dict(action="submit", ids=[True]),
            dict(action="submit", ids=[0]),
            dict(action="submit", ids=[2**53]),
            dict(action="submit", ids=[self.solution.pk] * 10001),
            dict(action="detach", ids=[self.solution.pk]),
            self.selection(force=True),
            [],
            None,
        ]
        for data in invalid:
            with self.subTest(data=str(data)[:100]):
                self.wire(
                    call(self.manager, "post", self.action_root + "preview/", data), 400
                )
        self.wire(
            call(
                self.manager,
                "post",
                self.action_root + "preview/?force=true",
                self.selection(),
            ),
            400,
        )

    def test_token_signature_actor_expiry_shape_and_replay(self):
        confirmation = self.confirmation()
        proof = signing.loads(confirmation["preview_token"], salt=actions.SALT)
        other_manager = create_user()
        self.program.managers.add(other_manager)
        response = self.apply(confirmation, actor=other_manager)
        self.assertEqual(self.wire(response, 409)["code"], "solution_action_conflict")
        from unittest.mock import patch

        for token in [
            "invalid",
            signing.dumps([], salt=actions.SALT),
            signing.dumps({**proof, "program": self.program.pk + 1}, salt=actions.SALT),
            signing.dumps({**proof, "ids": []}, salt=actions.SALT),
            signing.dumps({**proof, "action": "detach"}, salt=actions.SALT),
        ]:
            self.assertEqual(
                self.wire(self.apply({**confirmation, "preview_token": token}), 409)[
                    "code"
                ],
                "solution_action_conflict",
            )
        with patch(
            "django.core.signing.time.time", return_value=timezone.now().timestamp() + 601
        ):
            self.wire(self.apply(confirmation), 409)
        self.wire(self.apply(confirmation), schema="SolutionActionResult")
        after = self.saved()
        self.wire(self.apply(confirmation), 409)
        self.assertEqual(self.saved(), after)

    def test_saved_state_changes_invalidate_preview_even_without_solution_version_bump(
        self,
    ):
        upload = self.upload()
        self.assertEqual(
            self.save_answers(
                [{"field_id": self.fields["file"]["id"], "value": {"url": upload.link}}]
            ).status_code,
            200,
        )
        changes = [
            lambda: ProgramSolution.objects.filter(pk=self.solution.pk).update(
                name="Новое имя"
            ),
            lambda: self.solution.answers.filter(
                field_id=self.fields["textarea"]["id"]
            ).update(value="Новый ответ"),
            lambda: self.solution.members.update(role="Новая роль"),
            lambda: PartnerProgramField.objects.filter(
                pk=self.fields["textarea"]["id"]
            ).update(label="Другая подпись"),
            lambda: PartnerProgram.objects.filter(pk=self.program.pk).update(
                legacy_team_max_size=5
            ),
            lambda: UserFile.objects.filter(pk=upload.pk).update(size=101),
            lambda: get_user_model()
            .objects.filter(pk=self.captain.pk)
            .update(first_name="Новое имя"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index), transaction.atomic():
                confirmation = self.confirmation()
                change()
                before = self.saved()
                self.assertEqual(
                    self.wire(self.apply(confirmation), 409)["code"],
                    "solution_action_conflict",
                )
                self.assertEqual(self.saved(), before)
                transaction.set_rollback(True)

    def test_required_case_team_and_registration_still_block_preview(self):
        changes = [
            lambda: self.solution.answers.filter(
                field_id=self.fields["select"]["id"]
            ).delete(),
            lambda: self.solution.answers.filter(
                field_id=self.fields["select"]["id"]
            ).update(value="Несуществующий кейс"),
            lambda: PartnerProgram.objects.filter(pk=self.program.pk).update(
                legacy_team_min_size=2
            ),
            lambda: self.solution.answers.filter(
                field_id=self.fields["textarea"]["id"]
            ).delete(),
            lambda: ProgramSolutionMember.objects.create(
                solution=self.solution, user=create_user()
            ),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index), transaction.atomic():
                change()
                result = self.wire(self.preview())
                self.assertFalse(result["can_apply"])
                self.assertIsNone(result["preview_token"])
                self.assertTrue(result["items"][0]["errors"])
                self.assertEqual(self.saved()["status"], "draft")
                transaction.set_rollback(True)

    def test_unverified_file_failure_rolls_back_entire_bulk_after_first_finalization(
        self,
    ):
        other = self.another()
        upload = self.upload(user=other.captain, detected="")
        ProgramSolutionAnswer.objects.create(
            solution=other, field_id=self.fields["file"]["id"], value={"url": upload.link}
        )
        confirmation = self.confirmation([self.solution.pk, other.pk])
        before = [self.saved(), self.saved(other)]
        response = self.apply(confirmation)
        self.assertEqual(self.wire(response, 400)["code"], "invalid_answers")
        self.assertEqual([self.saved(), self.saved(other)], before)
        upload.refresh_from_db()
        self.assertEqual(upload.detected_mime_type, "")

    def test_creation_disabled_does_not_block_existing_ready_solution(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_creation_enabled=False
        )
        result = self.wire(self.apply(self.confirmation()), schema="SolutionActionResult")
        self.assertEqual(result["changed_count"], 1)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionSubmissionActionConcurrencyTests(ActionFixture, TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL program row locks")
        super().setUp()

    def run_race(self, commands):
        barrier, pids = Barrier(2), Queue()

        def worker(command):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.put(cursor.fetchone()[0])
                barrier.wait(timeout=10)
                try:
                    return command()
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
                futures = [pool.submit(worker, command) for command in commands]
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
            results = [future.result(timeout=20) for future in futures]
        return results

    def test_two_confirmations_wait_for_program_and_only_one_commits(self):
        data = self.confirmation()
        before = self.saved()
        results = self.run_race(
            [lambda: actions.apply(self.program.pk, self.manager, data)] * 2
        )
        self.assertEqual(results.count("solution_action_conflict"), 1)
        self.assertIn({"changed_count": 1, "already_submitted_count": 0}, results)
        after = self.saved()
        self.assertEqual(after["version"], before["version"] + 1)
        self.assertEqual(after["status"], "submitted")

    def test_confirmation_and_captain_patch_have_only_serialized_outcomes(self):
        data = self.confirmation()
        before = self.saved()
        name = self.solution.name

        def patch_materials():
            response = self.save_answers(name="Изменено после проверки")
            if response.status_code == 409:
                return response.data["code"]
            self.assertEqual(response.status_code, 200, response.data)
            return "patched"

        results = self.run_race(
            [lambda: actions.apply(self.program.pk, self.manager, data), patch_materials]
        )
        after = self.saved()
        self.assertEqual(after["version"], before["version"] + 1)
        if "patched" in results:
            self.assertIn("solution_action_conflict", results)
            self.assertEqual(after["status"], "draft")
            self.assertIsNone(after["snapshot"])
            self.assertEqual(self.solution.name, "Изменено после проверки")
        else:
            self.assertIn("team_frozen", results)
            self.assertIn({"changed_count": 1, "already_submitted_count": 0}, results)
            self.assertEqual(after["status"], "submitted")
            self.assertEqual(after["snapshot"]["name"], name)
