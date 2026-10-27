import hashlib
import json
from pathlib import Path

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from partner_programs.certificate_models import ProgramCertificate
from partner_programs.tests.helpers import create_user
from projects.models import Project


COMMON = ("partner_programs", "0030_program_solution_foundation")
SOLUTION = ("partner_programs", "0038_solution_registration_removal_audit")
CERTIFICATE = ("partner_programs", "0031_programcertificate_rendered_batch")
MERGED = ("partner_programs", "0039_merge_solution_certificate_branches")


def plain(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return json.loads(json.dumps(value, default=str))


class SolutionDevGraphTests(TestCase):
    def test_single_leaf_empty_merge_and_unchanged_upstream_migration(self):
        loader = MigrationLoader(None)
        self.assertEqual(loader.detect_conflicts(), {})
        leaves = loader.graph.leaf_nodes("partner_programs")
        self.assertEqual(len(leaves), 1)
        self.assertIn(MERGED, loader.graph.forwards_plan(leaves[0]))
        migration = loader.disk_migrations[MERGED]
        self.assertCountEqual(migration.dependencies, [CERTIFICATE, SOLUTION])
        self.assertEqual(migration.operations, [])
        source = (
            (
                Path(__file__).resolve().parents[1]
                / "migrations/0031_programcertificate_rendered_batch.py"
            )
            .read_bytes()
            .replace(b"\r\n", b"\n")
        )
        self.assertEqual(
            hashlib.sha256(source).hexdigest(),
            "2fe9364b189b5f7db866d67a77eb3d171a131f250215a621ac7bb280ec005e66",
        )
        field = ProgramCertificate._meta.get_field("rendered_batch")
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
        self.assertEqual(field.remote_field.related_name, "rendered_certificates")


class SolutionDevMigrationDataTests(TransactionTestCase):
    def setUp(self):
        self.latest = MigrationExecutor(connection).loader.graph.leaf_nodes()

    def before(self, branch):
        # Только isolated test DB: возвращаем обе ветки к общей точке, затем
        # применяем выбранный порядок. Main никогда не откатывается этим тестом.
        executor = MigrationExecutor(connection)
        executor.migrate([COMMON])
        targets = [branch]
        if branch == SOLUTION:
            targets.append(("project_rates", "0011_solution_score_value_1000"))
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def snapshot(self, model, fields=None):
        fields = fields or [field.attname for field in model._meta.concrete_fields]
        manager = getattr(model, "all_objects", model.objects)
        return json.dumps(
            plain(list(manager.order_by("pk").values(*fields))),
            sort_keys=True,
            ensure_ascii=False,
        )

    def seed(self, apps, branch):
        now = timezone.now()
        captain, member = create_user(), create_user()
        program_model = apps.get_model("partner_programs", "PartnerProgram")
        programs = []
        for index, mode in enumerate(["legacy_project", "solution"]):
            programs.append(
                program_model.objects.create(
                    name=f"Совместимость {mode}",
                    tag=f"dev-compat-{index}",
                    description="Исторические данные",
                    city="Москва",
                    data_schema={},
                    draft=False,
                    projects_availability="all_users",
                    solution_storage_mode=mode,
                    datetime_registration_ends=now,
                    datetime_started=now,
                    datetime_finished=now,
                )
            )
        legacy, program = programs
        project = Project(
            leader=captain,
            name="Старая заявка-проект",
            description="Не удалять",
            draft=False,
            is_public=False,
        )
        Project.objects.bulk_create([project])
        apps.get_model("partner_programs", "PartnerProgramProject").objects.create(
            partner_program_id=legacy.pk,
            project_id=project.pk,
            submitted=True,
            datetime_submitted=now,
        )
        apps.get_model("partner_programs", "PartnerProgramUserProfile").objects.create(
            partner_program_id=legacy.pk,
            user_id=captain.pk,
            project_id=project.pk,
            partner_program_data={"keep": [0, False]},
        )
        solution_model = apps.get_model("partner_programs", "ProgramSolution")
        payload = {"material": "Снимок без переинтерпретации", "zero": 0, "false": False}
        solution = solution_model.objects.create(
            program_id=program.pk,
            captain_id=captain.pk,
            name="Сданное решение",
            status="submitted",
            submitted_at=now,
            submission_snapshot=payload,
        )
        solution_model.objects.create(program_id=program.pk, captain_id=member.pk)
        apps.get_model("partner_programs", "ProgramSolutionMember").objects.create(
            solution_id=solution.pk, user_id=captain.pk, role="Капитан"
        )
        field_model = apps.get_model("partner_programs", "PartnerProgramField")
        for kind, value in [("number", 0), ("checkbox", False)]:
            field = field_model.objects.create(
                partner_program_id=program.pk,
                name=kind,
                field_type=kind,
                purpose="other",
                label=kind,
                is_required=False,
            )
            apps.get_model("partner_programs", "ProgramSolutionAnswer").objects.create(
                solution_id=solution.pk, field_id=field.pk, value=value
            )
        apps.get_model("partner_programs", "SolutionInvitation").objects.create(
            solution_id=solution.pk,
            recipient_id=member.pk,
            role="Дизайнер",
            status="declined",
        )
        if branch == SOLUTION:
            archived = solution_model.objects.create(
                program_id=program.pk,
                captain_id=captain.pk,
                name="Архив",
                version=2,
                status="submitted",
                submitted_at=now,
                submission_snapshot=payload,
                archived_at=now,
                archived_by_id=captain.pk,
                archive_reason="detached",
                archive_snapshot=payload,
            )
            apps.get_model(
                "partner_programs", "SolutionAdministrativeChange"
            ).objects.create(
                solution_id=archived.pk,
                actor_id=captain.pk,
                actor_name="Организатор",
                action="archive",
                before_version=1,
                after_version=2,
                was_submitted=True,
                before_snapshot=payload,
                after_snapshot=payload,
                archived_at=now,
                archive_reason="detached",
                archive_snapshot=payload,
            )
            apps.get_model(
                "partner_programs", "SolutionRegistrationRemoval"
            ).objects.create(
                program_id=program.pk,
                actor_id=captain.pk,
                actor_name="Организатор",
                registrations=[{"registration_id": 999, "user": {"id": member.pk}}],
                deleted_count=1,
            )
            for kind, value in [("int", "0"), ("bool", "False")]:
                criterion = apps.get_model("project_rates", "Criteria").objects.create(
                    partner_program_id=program.pk, name=kind, type=kind
                )
                apps.get_model("project_rates", "SolutionScore").objects.create(
                    solution_id=solution.pk,
                    criteria_id=criterion.pk,
                    user_id=captain.pk,
                    value=value,
                )
        batch_model = apps.get_model("partner_programs", "ProgramCertificateBatch")
        batches = [
            batch_model.objects.create(
                program_id=legacy.pk,
                snapshot={"version": index, "keep": False},
                issue_at=now,
                public_base_url="https://local.test",
            )
            for index in [1, 2]
        ]
        certificate_model = apps.get_model("partner_programs", "ProgramCertificate")
        options = dict(rendered_batch_id=batches[0].pk) if branch == CERTIFICATE else {}
        pdf = certificate_model.objects.create(
            program_id=legacy.pk,
            user_id=captain.pk,
            batch_id=batches[1].pk,
            name="Старая версия PDF",
            email=captain.email,
            pdf=b"%PDF-1.4\noriginal-version\n%%EOF",
            status="sent",
            **options,
        )
        pending = certificate_model.objects.create(
            program_id=legacy.pk,
            user_id=member.pk,
            batch_id=batches[1].pk,
            name="Без PDF",
            email=member.email,
        )
        return (
            pdf.pk,
            pending.pk,
            batches[0].pk if branch == CERTIFICATE else batches[1].pk,
        )

    def assert_order_preserves_data(self, branch):
        try:
            apps = self.before(branch)
            pdf, pending, expected_batch = self.seed(apps, branch)
            labels = [
                "PartnerProgram",
                "PartnerProgramProject",
                "PartnerProgramUserProfile",
                "ProgramSolution",
                "ProgramSolutionMember",
                "ProgramSolutionAnswer",
                "SolutionInvitation",
                "PartnerProgramField",
                "ProgramCertificateBatch",
                "ProgramCertificate",
            ]
            if branch == SOLUTION:
                labels += ["SolutionAdministrativeChange", "SolutionRegistrationRemoval"]
            before = {}
            for label in labels:
                model = apps.get_model("partner_programs", label)
                fields = [field.attname for field in model._meta.concrete_fields]
                before[label] = fields, self.snapshot(model, fields)
            projects = json.dumps(
                plain(list(Project.objects.order_by("pk").values())), sort_keys=True
            )
            scores = (
                self.snapshot(apps.get_model("project_rates", "SolutionScore"))
                if branch == SOLUTION
                else None
            )
            executor = MigrationExecutor(connection)
            executor.migrate(self.latest)
            after_apps = executor.loader.project_state(self.latest).apps
            for label, (fields, rows) in before.items():
                self.assertEqual(
                    self.snapshot(
                        after_apps.get_model("partner_programs", label), fields
                    ),
                    rows,
                    label,
                )
            self.assertEqual(
                json.dumps(
                    plain(list(Project.objects.order_by("pk").values())), sort_keys=True
                ),
                projects,
            )
            if scores is not None:
                self.assertEqual(
                    self.snapshot(after_apps.get_model("project_rates", "SolutionScore")),
                    scores,
                )
            model = after_apps.get_model("partner_programs", "ProgramCertificate")
            self.assertEqual(model.objects.get(pk=pdf).rendered_batch_id, expected_batch)
            self.assertIsNone(model.objects.get(pk=pending).rendered_batch_id)
            self.assertEqual(MigrationLoader(connection).detect_conflicts(), {})
        finally:
            MigrationExecutor(connection).migrate(self.latest)

    def test_solution_first_preserves_projects_snapshots_scores_and_history(self):
        self.assert_order_preserves_data(SOLUTION)

    def test_certificate_first_preserves_original_pdf_batch_and_solutions(self):
        self.assert_order_preserves_data(CERTIFICATE)
