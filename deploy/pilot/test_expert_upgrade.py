from contextlib import redirect_stdout
from copy import deepcopy
import io
import hashlib
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import upgrade_expert as upgrade


class ExpertBundleTests(unittest.TestCase):
    def test_verified_bundle_rejects_mutation_extra_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            base = {
                key: str(index) * 40
                for index, key in enumerate(
                    (
                        "backend_revision",
                        "frontend_revision",
                        "base_backend_revision",
                        "base_frontend_revision",
                    ),
                    start=1,
                )
            }
            api = b"# owned API patch\n"
            index = (
                b'<html data-theme="light"><meta content="white-label-pilot-v1"></html>'
            )
            digest = lambda data: hashlib.sha256(data).hexdigest()  # noqa: E731
            base.update(
                target_hashes={"patch.py": digest(api)},
                frontend_files={"index.html": digest(b"old")},
                target_frontend_files={"index.html": digest(index)},
            )
            (root / "api").mkdir()
            (root / "frontend").mkdir()
            (root / "api/patch.py").write_bytes(api)
            (root / "frontend/index.html").write_bytes(index)
            (root / "expert_base.json").write_text(json.dumps(base))
            manifest = {
                "format": upgrade.IDENTITY,
                **{key: value for key, value in base.items() if key.endswith("revision")},
                "tooling_revision": "f" * 40,
                "new_files": base["target_frontend_files"],
                "files": {
                    str(p.relative_to(root)): digest(p.read_bytes())
                    for p in root.rglob("*")
                    if p.is_file()
                },
            }
            (root / "expert-manifest.json").write_text(json.dumps(manifest))
            with patch.object(upgrade, "BASE", base), patch.object(
                upgrade, "PATCH_FILES", ("patch.py",)
            ), patch.object(upgrade, "HELPERS", {"expert_base.json"}):
                self.assertEqual(upgrade.verify_bundle(root), manifest)
                (root / "api/patch.py").write_bytes(b"changed")
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_bundle(root)
                (root / "api/patch.py").write_bytes(api)
                extra = root / "extra.txt"
                extra.write_bytes(b"unexpected")
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_bundle(root)
                extra.unlink()
                extra.symlink_to(root / "api/patch.py")
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_bundle(root)


class ExpertUpgradeGuardTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "containers": {
                name: [name, "image", "started", "config"]
                for name in upgrade.overall.OUTSIDE
            },
            "files": {"pilot.env": "original"},
            "nginx": "original",
            "network": {"Id": "original"},
        }
        self.record = {"old_container_id": "old-web", "outside": deepcopy(self.snapshot)}

    def test_historical_dev_restart_does_not_rewrite_the_accepted_pilot_snapshot(self):
        original = deepcopy(self.record)
        for name in upgrade.previous.DEV_CONTAINERS:
            self.snapshot["containers"][name] = [
                "new-id",
                "new-image",
                "new-start",
                "new-config",
            ]
        with patch.object(upgrade.hosted, "inspect"), patch.object(
            upgrade.previous, "outside_snapshot", return_value=self.snapshot
        ), patch.object(upgrade.hosted, "dev_health", return_value=200):
            self.assertEqual(upgrade.verify_predecessor(self.record), 200)
        self.assertEqual(self.record, original)

    def test_pilot_database_network_files_and_nginx_drift_is_rejected(self):
        for field in ("files", "nginx", "network"):
            changed = deepcopy(self.snapshot)
            changed[field] = {"unexpected": True}
            with self.subTest(field=field), patch.object(
                upgrade.hosted, "inspect"
            ), patch.object(upgrade.previous, "outside_snapshot", return_value=changed):
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_predecessor(self.record)
        changed = deepcopy(self.snapshot)
        changed["containers"][upgrade.hosted.PG][0] = "other-database-container"
        with patch.object(upgrade.hosted, "inspect"), patch.object(
            upgrade.previous, "outside_snapshot", return_value=changed
        ):
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.verify_predecessor(self.record)

    def test_current_dev_change_is_rejected_during_the_update(self):
        changed = deepcopy(self.snapshot)
        changed["containers"]["api-web-1"][0] = "changed-during-apply"
        with patch.object(upgrade.hosted, "inspect"), patch.object(
            upgrade, "outside_snapshot", return_value=changed
        ), patch.object(upgrade.hosted, "dev_health") as health:
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.verify_outside(self.record)
            health.assert_not_called()


class ExpertMigrationTests(unittest.TestCase):
    def operation(self, name="RunPython"):
        def create_organizer_expert_identities():
            pass

        return type(
            name, (), {"code": staticmethod(create_organizer_expert_identities)}
        )()

    def migration(self, name, operations):
        return SimpleNamespace(
            app_label="partner_programs", name=name, operations=operations
        )

    def simulate(self, plan, *, wrong_database=False):
        applied = [False]
        calls = []
        constructors = []
        test = self

        class Executor:
            def __init__(self, connection):
                constructors.append(True)
                self.original = [] if applied[0] else plan
                self.loader = SimpleNamespace(
                    graph=SimpleNamespace(
                        leaf_nodes=lambda: [("partner_programs", "leaf")]
                    )
                )

            def migration_plan(self, targets):
                return list(self.original)

            def migrate(self, targets):
                calls.append(targets)
                applied[0] = True

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                test.assertIn(
                    sql, ("SET lock_timeout = '10s'", "SET statement_timeout = '120s'")
                )

        def module(name, **values):
            value = ModuleType(name)
            value.__dict__.update(values)
            return value

        connection = SimpleNamespace(
            settings_dict={
                "NAME": "wrong" if wrong_database else upgrade.hosted.DB_NAME,
                "USER": upgrade.hosted.DB_ROLE,
                "HOST": "db",
            },
            cursor=Cursor,
        )
        modules = {
            "django": module(
                "django", setup=lambda: None, get_version=lambda: "test-runtime"
            ),
            "django.db": module("django.db", connection=connection),
            "django.db.migrations": module("django.db.migrations"),
            "django.db.migrations.executor": module(
                "django.db.migrations.executor", MigrationExecutor=Executor
            ),
        }

        def docker(*args, **kwargs):
            output = io.StringIO()
            try:
                with patch.dict("sys.modules", modules), redirect_stdout(output):
                    exec(args[args.index("-c") + 1], {})
                return SimpleNamespace(returncode=0, stdout=output.getvalue())
            except AssertionError:
                return SimpleNamespace(returncode=1, stdout="")

        with patch.object(upgrade.hosted, "docker", side_effect=docker):
            try:
                result = upgrade.migrate({"Id": "owned-pilot"})
            except upgrade.hosted.Refused:
                self.assertEqual(calls, [])
                raise
        return result, calls, constructors

    def test_only_two_additive_migrations_run_and_postcheck_uses_a_fresh_loader(self):
        plan = [
            (
                self.migration("0044_organizer_expert_identities", [self.operation()]),
                False,
            ),
            (self.migration("0046_merge_organizer_experts_and_quiz", []), False),
        ]
        result, calls, constructors = self.simulate(plan)
        self.assertEqual(len(result["migrations_applied"]), 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(constructors), 2)

    def test_reapply_after_rollback_accepts_already_applied_additive_migrations(self):
        result, _, _ = self.simulate([])
        self.assertEqual(result["migrations_applied"], [])

    def test_unexpected_reverse_or_schema_migrations_are_never_executed(self):
        cases = [
            [(self.migration("0047_unexpected", []), False)],
            [
                (
                    self.migration(
                        "0044_organizer_expert_identities", [self.operation()]
                    ),
                    True,
                )
            ],
            [
                (
                    self.migration(
                        "0044_organizer_expert_identities", [self.operation("RunSQL")]
                    ),
                    False,
                )
            ],
            [
                (
                    self.migration(
                        "0046_merge_organizer_experts_and_quiz",
                        [self.operation("CreateModel")],
                    ),
                    False,
                )
            ],
        ]
        for plan in cases:
            with self.subTest(name=plan[0][0].name), self.assertRaises(
                upgrade.hosted.Refused
            ):
                self.simulate(plan)

    def test_wrong_database_is_rejected_before_migration(self):
        with self.assertRaises(upgrade.hosted.Refused):
            self.simulate([], wrong_database=True)


if __name__ == "__main__":
    unittest.main()
