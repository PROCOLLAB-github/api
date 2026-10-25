"""REL01: остановка только нового создания без потери действующих решений."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from queue import Queue
from time import monotonic, sleep

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram
from partner_programs.solution_api import create_solution
from partner_programs.solution_errors import MAX_ID, SolutionError
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
    project_apply_payload,
)
from partner_programs.tests.test_solution_foundation import solution_program
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_publication import PublicationFixture
from partner_programs.tests.test_solution_submission import SubmissionFixture
from project_rates.tests.test_solution_evaluation import EvaluationFixture
from projects.models import Project

FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def toggle(program_id, enabled, *, apply=True):
    output = StringIO()
    arguments = ["--program-id", str(program_id), "--enable" if enabled else "--disable"]
    if apply:
        arguments.append("--apply")
    call_command("set_solution_creation", *arguments, stdout=output)
    return json.loads(output.getvalue())


def domain_state(model_registry=None):
    selected = (
        ProgramSolution,
        ProgramSolutionAnswer,
        ProgramSolutionMember,
        SolutionInvitation,
        Project,
    )
    if model_registry is not None:
        selected = tuple(
            model_registry.get_model(model._meta.label) for model in selected
        )
    return {
        model._meta.label: list(model.objects.order_by("pk").values())
        for model in selected
    }


def assert_schema(name, data):
    from jsonschema import Draft202012Validator, FormatChecker

    spec = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/contracts/program-solutions-v1/openapi.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(
        {"components": spec["components"], "$ref": f"#/components/schemas/{name}"},
        format_checker=FormatChecker(),
    ).validate(data)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionCreationSwitchTests(TestCase):
    def setUp(self):
        self.program = solution_program(
            solution_creation_enabled=False, is_competitive=True
        )
        self.captain = create_user()
        create_program_member(self.program, user=self.captain)
        self.url = f"/programs/{self.program.pk}/solutions/"
        self.context_url = f"/programs/{self.program.pk}/solution-context/"

    def test_default_is_disabled_and_flag_is_not_a_client_setting(self):
        program = create_partner_program(solution_storage_mode="solution")
        self.assertFalse(program.solution_creation_enabled)
        self.assertEqual(create_partner_program().solution_storage_mode, "legacy_project")
        field = PartnerProgram._meta.get_field("solution_creation_enabled")
        self.assertFalse(field.editable)
        from partner_programs.serializers.programs import (
            PartnerProgramForMemberSerializer,
            PartnerProgramForUnregisteredUserSerializer,
        )

        for serializer in (
            PartnerProgramForMemberSerializer,
            PartnerProgramForUnregisteredUserSerializer,
        ):
            self.assertNotIn("solution_creation_enabled", serializer().fields)

    def test_disabled_context_and_post_agree_without_domain_writes(self):
        before = domain_state()
        context = call(self.captain, "get", self.context_url)
        self.assertEqual(context.status_code, 200)
        self.assertFalse(context.data["can_create"])
        self.assertEqual(context.data["blocked_reason"], "solution_creation_disabled")
        self.assertTrue(context.data["submission_open"])
        self.assertIsNone(context.data["current_application"])
        assert_schema("Context", context.data)
        result = call(self.captain, "post", self.url)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.data["code"], "solution_creation_disabled")
        assert_schema("Error", result.data)
        self.assertEqual(domain_state(), before)

    def test_enable_disable_reenable_is_scoped_and_repeat_captain_is_unchanged(self):
        other = solution_program()
        other_user = create_user()
        create_program_member(other, user=other_user)
        self.assertEqual(
            call(other_user, "post", f"/programs/{other.pk}/solutions/").status_code,
            201,
        )
        toggle(self.program.pk, True)
        self.assertTrue(call(self.captain, "get", self.context_url).data["can_create"])
        created = call(self.captain, "post", self.url, {"name": "Первая заявка"})
        self.assertEqual(created.status_code, 201, created.data)
        before = domain_state()
        toggle(self.program.pk, False)
        repeated = call(self.captain, "post", self.url, {"name": "Не менять"})
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data, created.data)
        self.assertEqual(domain_state(), before)
        context = call(self.captain, "get", self.context_url).data
        self.assertEqual(context["blocked_reason"], "already_has_application")
        self.assertEqual(
            context["current_application"]["solution_id"], created.data["id"]
        )
        newcomer = create_user()
        create_program_member(self.program, user=newcomer)
        self.assertEqual(call(newcomer, "post", self.url).status_code, 409)
        toggle(self.program.pk, True)
        self.assertEqual(call(newcomer, "post", self.url).status_code, 201)
        other.refresh_from_db()
        self.assertTrue(other.solution_creation_enabled)
        self.assertEqual(ProgramSolution.objects.count(), 3)
        self.assertFalse(Project.objects.exists())

    def test_accepted_member_opens_current_application_without_second_creation(self):
        toggle(self.program.pk, True)
        created = call(self.captain, "post", self.url).data
        member = create_user()
        create_program_member(self.program, user=member)
        ProgramSolutionMember.objects.create(solution_id=created["id"], user=member)
        toggle(self.program.pk, False)
        context = call(member, "get", self.context_url).data
        self.assertEqual(context["current_application"]["solution_id"], created["id"])
        self.assertEqual(context["blocked_reason"], "already_has_application")
        result = call(member, "post", self.url)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.data["code"], "already_in_program_team")
        self.assertEqual(ProgramSolution.objects.count(), 1)

    def test_rights_precede_switch_and_switch_precedes_deadline_and_form(self):
        self.assertEqual(APIClient().post(self.url, {}, format="json").status_code, 401)
        for outsider in [create_user(), create_user(is_staff=True)]:
            context = call(outsider, "get", self.context_url).data
            self.assertEqual(context["blocked_reason"], "not_program_member")
            result = call(outsider, "post", self.url)
            self.assertEqual(result.status_code, 403)
            self.assertEqual(result.data["code"], "not_program_member")
        manager = create_user()
        self.program.managers.add(manager)
        self.assertEqual(
            call(manager, "post", self.url).data["code"], "solution_creation_disabled"
        )
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(days=1)
        )
        self.program.save(update_fields=["datetime_project_submission_ends"])
        for actor in [self.captain, manager]:
            self.assertEqual(
                call(actor, "get", self.context_url).data["blocked_reason"],
                "solution_creation_disabled",
            )
            self.assertEqual(
                call(actor, "post", self.url).data["code"], "solution_creation_disabled"
            )
        toggle(self.program.pk, True)
        self.assertEqual(
            call(self.captain, "post", self.url).data["code"], "submission_closed"
        )
        self.program.datetime_project_submission_ends = None
        self.program.solution_template = None
        self.program.save(
            update_fields=["datetime_project_submission_ends", "solution_template"]
        )
        self.assertEqual(
            call(self.captain, "post", self.url).data["code"], "form_not_configured"
        )
        toggle(self.program.pk, False)
        self.assertEqual(
            call(self.captain, "get", self.context_url).data["blocked_reason"],
            "solution_creation_disabled",
        )

    def test_client_cannot_override_switch_and_unknown_program_remains_hidden(self):
        result = call(self.captain, "post", self.url, {"solution_creation_enabled": True})
        self.assertEqual(result.status_code, 400)
        for program_id in [MAX_ID, MAX_ID + 1, 0]:
            result = call(self.captain, "post", f"/programs/{program_id}/solutions/")
            self.assertEqual(result.status_code, 404)
        self.assertFalse(ProgramSolution.objects.exists())

    def test_legacy_creation_is_unchanged_while_switch_is_disabled(self):
        program = create_partner_program()
        create_program_member(program, user=self.captain)
        context = call(
            self.captain, "get", f"/programs/{program.pk}/solution-context/"
        ).data
        self.assertEqual(context["blocked_reason"], "legacy_mode")
        result = call(
            self.captain,
            "post",
            f"/programs/{program.pk}/projects/apply/",
            project_apply_payload(),
        )
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(Project.objects.count(), 1)
        self.assertFalse(ProgramSolution.objects.exists())


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionCreationCommandTests(TestCase):
    def test_stale_program_save_does_not_override_either_operator_switch(self):
        program = solution_program()
        toggle(program.pk, False)
        program.description = "Изменение обычной карточки"
        program.save()
        program.refresh_from_db()
        self.assertFalse(program.solution_creation_enabled)
        toggle(program.pk, True)
        program.name = "Другая подпись"
        program.save()
        program.refresh_from_db()
        self.assertTrue(program.solution_creation_enabled)
        self.assertEqual(program.description, "Изменение обычной карточки")

    def test_preview_apply_idempotency_and_only_one_column_changes(self):
        program, other = solution_program(), solution_program()
        captain = create_user()
        create_program_member(program, user=captain)
        create_solution(program.pk, captain, {})
        before = domain_state()
        metadata = list(PartnerProgram.objects.order_by("pk").values())
        preview = toggle(program.pk, False, apply=False)
        self.assertFalse(preview["applied"])
        self.assertFalse(preview["changed"])
        self.assertEqual(list(PartnerProgram.objects.order_by("pk").values()), metadata)
        receipt = toggle(program.pk, False)
        self.assertTrue(receipt["changed"])
        self.assertTrue(receipt["previous_enabled"])
        self.assertFalse(receipt["requested_enabled"])
        metadata[0]["solution_creation_enabled"] = False
        self.assertEqual(list(PartnerProgram.objects.order_by("pk").values()), metadata)
        self.assertFalse(toggle(program.pk, False)["changed"])
        self.assertEqual(domain_state(), before)
        other.refresh_from_db()
        self.assertTrue(other.solution_creation_enabled)

    def test_invalid_unknown_ids_and_legacy_enable_do_not_write(self):
        program = create_partner_program()
        before = list(PartnerProgram.objects.values())
        for identifier in [-1, 0, MAX_ID, MAX_ID + 1, program.pk]:
            with self.subTest(identifier=identifier), self.assertRaises(CommandError):
                toggle(identifier, True)
        self.assertEqual(list(PartnerProgram.objects.values()), before)
        self.assertFalse(toggle(program.pk, False)["changed"])


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, SELECTEL_SWIFT_URL="https://cdn.test")
class SolutionCreationExistingDraftTests(SubmissionFixture, TestCase):
    def setUp(self):
        self.ready()
        toggle(self.program.pk, False)

    def invite(self):
        user = create_user()
        create_program_member(self.program, user=user)
        self.solution.refresh_from_db()
        result = call(
            self.captain,
            "post",
            self.url + "invitations/",
            dict(
                recipient_user_id=user.pk,
                expected_solution_version=self.solution.version,
                role="Разработчик",
            ),
        )
        self.assertEqual(result.status_code, 201, result.data)
        return user, result.data["invitation"]

    def accept(self, user, invitation):
        result = call(
            user,
            "post",
            f"/solution-invitations/{invitation['id']}/accept/",
            {"expected_version": invitation["version"]},
        )
        self.assertEqual(result.status_code, 200, result.data)

    def test_existing_save_file_invite_accept_submit_and_pending_cleanup_continue(self):
        upload = self.upload()
        result = self.save_answers(
            [{"field_id": self.fields["file"]["id"], "value": {"url": upload.pk}}],
            name="Работа продолжается",
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data["permissions"]["can_edit"])
        member, invitation = self.invite()
        self.solution.refresh_from_db()
        edited = call(
            self.captain,
            "patch",
            f"/solution-invitations/{invitation['id']}/",
            dict(
                expected_version=invitation["version"],
                expected_solution_version=self.solution.version,
                role="Аналитик",
            ),
        )
        self.assertEqual(edited.status_code, 200, edited.data)
        self.accept(member, edited.data["invitation"])
        declined_user, declined = self.invite()
        _, revoked = self.invite()
        result = self.submit()
        self.assertEqual(result.status_code, 200, result.data)
        assert_schema("Solution", result.data)
        self.solution.refresh_from_db()
        snapshot = copy.deepcopy(self.solution.submission_snapshot)
        self.assertEqual(result.data["team"]["accepted_count"], 2)
        self.assertEqual(result.data["name"], "Работа продолжается")
        self.assertFalse(result.data["permissions"]["can_edit"])
        self.assertEqual(self.save_answers(name="Запрещено").status_code, 409)
        self.assertEqual(self.submit().data["code"], "already_submitted")
        self.assertEqual(
            call(
                declined_user,
                "post",
                f"/solution-invitations/{declined['id']}/decline/",
                {"expected_version": declined["version"]},
            ).status_code,
            200,
        )
        self.solution.refresh_from_db()
        self.assertEqual(
            call(
                self.captain,
                "delete",
                f"/solution-invitations/{revoked['id']}/?expected_version={revoked['version']}"
                f"&expected_solution_version={self.solution.version}",
            ).status_code,
            204,
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.submission_snapshot, snapshot)
        for actor in [self.captain, member, self.manager]:
            read = call(actor, "get", self.url)
            self.assertEqual(read.status_code, 200)
            self.assertEqual(read.data["answers"], snapshot["answers"])
        self.assertFalse(self.solution.invitations.filter(status="pending").exists())
        self.program.refresh_from_db()
        self.assertFalse(self.program.solution_creation_enabled)

    def test_existing_transfer_remove_and_leave_keep_their_rules(self):
        member, invitation = self.invite()
        self.accept(member, invitation)
        removable, invitation = self.invite()
        self.accept(removable, invitation)
        self.solution.refresh_from_db()
        result = call(
            self.captain,
            "delete",
            self.url
            + f"members/{removable.pk}/?expected_solution_version={self.solution.version}",
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.solution.refresh_from_db()
        result = call(
            self.captain,
            "post",
            self.url + "captain/",
            dict(
                new_captain_user_id=member.pk,
                expected_solution_version=self.solution.version,
            ),
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.captain_id, member.pk)
        result = call(
            self.captain,
            "post",
            self.url + "leave/",
            {"expected_solution_version": self.solution.version},
        )
        self.assertEqual(result.status_code, 204, result.data)
        self.assertEqual(
            list(self.solution.members.values_list("user_id", flat=True)), [member.pk]
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionCreationExistingReadersTests(EvaluationFixture, TestCase):
    def test_expert_evaluation_and_manager_results_continue_while_creation_disabled(self):
        self.seed_evaluation()
        toggle(self.program.pk, False)
        self.assertEqual(call(self.expert, "get", self.evaluation_url).status_code, 200)
        self.assertEqual(self.rate().status_code, 200)
        self.assertEqual(call(self.expert, "get", self.list_url).status_code, 200)
        self.assertEqual(
            call(
                self.manager,
                "get",
                f"/programs/{self.program.pk}/management/solution-results/",
            ).status_code,
            200,
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionCreationExistingPublicTests(PublicationFixture, TestCase):
    def test_noncompetitive_publisher_and_anonymous_materials_ignore_creation_switch(
        self,
    ):
        self.seed_publication()
        toggle(self.program.pk, False)
        self.assertEqual(self.publish(), 1)
        self.assertEqual(self.read()["count"], 1)
        self.assertEqual(
            self.read(self.solution)["application"]["solution_id"], self.solution.pk
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionCreationSwitchMigrationTests(SubmissionFixture, TransactionTestCase):
    def test_existing_programs_and_solution_data_survive_disabled_default(self):
        self.ready()
        self.assertEqual(self.submit().status_code, 200)
        create_partner_program()
        columns = [
            f.attname
            for f in PartnerProgram._meta.fields
            if f.name != "solution_creation_enabled"
        ]
        before_programs = list(PartnerProgram.objects.order_by("pk").values(*columns))
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [("partner_programs", "0033_solution_publication")]
        after = [("partner_programs", "0034_solution_creation_switch")]
        historical = executor.loader.project_state(after).apps
        before_data = domain_state(historical)
        try:
            executor.migrate(before)
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            self.assertFalse(
                PartnerProgram.objects.filter(solution_creation_enabled=True).exists()
            )
            self.assertEqual(
                list(PartnerProgram.objects.order_by("pk").values(*columns)),
                before_programs,
            )
            self.assertEqual(domain_state(historical), before_data)
        finally:
            MigrationExecutor(connection).migrate(latest)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionCreationSwitchConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks")
        self.program = solution_program(is_competitive=True)
        self.captain = create_user()
        create_program_member(self.program, user=self.captain)

    def assert_worker_blocked(self, worker_pid):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            main_pid = cursor.fetchone()[0]
            until = monotonic() + 10
            while monotonic() < until:
                cursor.execute("SELECT pg_blocking_pids(%s)", [worker_pid])
                if main_pid in cursor.fetchone()[0]:
                    return
                sleep(0.01)
        self.fail("Worker did not wait for the program row lock")

    def worker(self, ready, action):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                ready.put(cursor.fetchone()[0])
            return action()
        finally:
            close_old_connections()

    def test_create_waiting_for_disable_lock_rechecks_committed_flag(self):
        def create():
            try:
                create_solution(self.program.pk, self.captain, {})
            except SolutionError as error:
                return error.payload["code"]
            return "created"

        ready = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                PartnerProgram.objects.select_for_update().get(pk=self.program.pk)
                toggle(self.program.pk, False)
                future = pool.submit(self.worker, ready, create)
                self.assert_worker_blocked(ready.get(timeout=10))
            self.assertEqual(future.result(timeout=15), "solution_creation_disabled")
        self.assertFalse(ProgramSolution.objects.exists())
        self.assertFalse(ProgramSolutionMember.objects.exists())

    def test_disable_waits_for_created_solution_and_preserves_existing_access(self):
        ready = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                solution, created = create_solution(self.program.pk, self.captain, {})
                self.assertTrue(created)
                future = pool.submit(
                    self.worker, ready, lambda: toggle(self.program.pk, False)
                )
                self.assert_worker_blocked(ready.get(timeout=10))
            self.assertTrue(future.result(timeout=15)["changed"])
        repeated, created = create_solution(self.program.pk, self.captain, {})
        self.assertFalse(created)
        self.assertEqual(repeated.pk, solution.pk)
        self.assertEqual(ProgramSolution.objects.count(), 1)
        self.assertEqual(ProgramSolutionMember.objects.count(), 1)
