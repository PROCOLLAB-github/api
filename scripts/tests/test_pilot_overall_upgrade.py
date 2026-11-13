"""Сохранность пилота при установке и при ошибках миграции/публикации рейтинга."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[2] / "deploy/pilot"
with patch.object(sys, "path", [str(SOURCE), *sys.path]):
    upgrade = importlib.import_module("upgrade_overall")
    packager = importlib.import_module("package_overall")
    unpacker = importlib.import_module("unpack_candidate")
VERIFY_RUNTIME = upgrade.verify_runtime


class OverallUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.root = self.directory / "pilot"
        self.root.mkdir()
        (self.root / "backup").mkdir()
        (self.root / "frontend").mkdir()
        (self.root / "data").mkdir()
        (self.root / "logs").mkdir()
        self.old = {
            "index.html": b"old auth index",
            "main-old.js": b"old code",
            "assets/logo.svg": b"logo",
        }
        self.new = {
            "index.html": b'<meta content="white-label-pilot-v1"><meta content="noindex, nofollow">overall',
            "main-new.js": b"new code",
            "assets/logo.svg": b"logo",
        }
        for name, data in self.old.items():
            target = self.root / "frontend" / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(data)
        self.base = deepcopy(upgrade.BASE)
        self.base["frontend_files"] = {
            name: self.hash(data) for name, data in self.old.items()
        }
        self.base["target_frontend_files"] = {
            name: self.hash(data) for name, data in self.new.items()
        }
        self.base["runtime_hashes"] = {name: None for name in upgrade.PATCH_FILES}
        self.base["target_hashes"] = {
            name: self.hash(("new " + name).encode()) for name in upgrade.PATCH_FILES
        }
        self.mounts = [
            {
                "Type": "bind",
                "Source": str(self.root / "data"),
                "Destination": "/procollab/pilot-data",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": str(self.root / "logs"),
                "Destination": "/procollab/log",
                "RW": True,
            },
        ]
        for name in self.base["overlays"]:
            source = self.root / "releases" / "old" / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("old " + name)
            self.base["runtime_hashes"][name] = upgrade.hosted.digest(source)
            self.mounts.append(
                {
                    "Type": "bind",
                    "Source": str(source),
                    "Destination": "/procollab/" + name,
                    "RW": False,
                }
            )
        self.before = {
            "Id": "1" * 64,
            "Image": "sha256:" + "2" * 64,
            "Config": {
                "Hostname": "old-host",
                "Image": "old-image-name",
                "Env": ["TEST=unchanged", "OTHER=still"],
                "Labels": {
                    upgrade.hosted.LABEL: upgrade.hosted.IDENTITY,
                    upgrade.files.REVISION_LABEL: self.base["base_backend_revision"],
                },
            },
            "HostConfig": {"Mounts": ["old"], "Memory": 768 * 2**20},
            "Mounts": self.mounts,
            "State": {"Running": True, "StartedAt": "original-start"},
        }
        self.containers = {self.before["Id"]: self.before}
        self.names = {upgrade.hosted.WEB: self.before["Id"]}
        self.calls = []
        self.state = {
            "identity": upgrade.hosted.IDENTITY,
            "phase": "active",
            "image_id": self.before["Image"],
            "app_patch_revision": self.base["base_backend_revision"],
            "weights_revision": self.base["base_backend_revision"],
            "app_patch_files": {"old-overlay": "kept"},
        }
        (self.root / ".env").write_text("TEST=unchanged\n")
        (self.root / "access.txt").write_text("Пароль входа: fake-local-gate\n")
        (self.root / "data" / "case-sentinel").write_text("existing scores / team / PDF")
        self.route, self.maps = self.root / "routes.inc", self.root / "maps.conf"
        self.route.write_text("unchanged routes")
        self.maps.write_text("unchanged maps")
        self.state.update(
            new_routes_sha256=upgrade.hosted.digest(self.route),
            new_maps_sha256=upgrade.hosted.digest(self.maps),
        )
        (self.root / "state.json").write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2)
        )
        (self.root / "invite-upgrade.json").write_text("old invite record")
        (self.root / "weights-upgrade.json").write_text(
            json.dumps(
                {
                    "identity": "hosted-v2-weights-upgrade",
                    "phase": "active",
                    "release": self.base["base_backend_revision"],
                    "candidate_id": self.before["Id"],
                }
            )
        )
        auth_record = {
            "identity": upgrade.auth.IDENTITY,
            "release": self.base["base_frontend_revision"],
            "phase": "active",
            "backup": str(self.root / "backup" / ("auth-" + "0" * 12)),
            "new_files": self.base["frontend_files"],
            "frontend": {
                "index.html": {
                    "before": "0" * 64,
                    "after": self.base["frontend_files"]["index.html"],
                }
            },
            "protected": {
                "format": upgrade.auth.SNAPSHOT_FORMAT,
                "containers": {
                    upgrade.hosted.WEB: upgrade.container_identity(self.before)
                },
                "files": {
                    str(self.root / name): upgrade.hosted.digest(self.root / name)
                    for name in (
                        ".env",
                        "state.json",
                        "access.txt",
                        "weights-upgrade.json",
                    )
                },
            },
        }
        (self.root / "frontend-upgrade.json").write_text(json.dumps(auth_record))
        self.enterContext(patch.object(upgrade, "BASE", self.base))
        self.enterContext(patch.object(upgrade, "ROOT", self.root))
        self.enterContext(
            patch.object(upgrade, "RECORD", self.root / "overall-upgrade.json")
        )
        self.enterContext(patch.object(upgrade.hosted, "NEW", self.root))
        self.enterContext(patch.object(upgrade.hosted, "ROUTES", self.route))
        self.enterContext(patch.object(upgrade.hosted, "MAPS", self.maps))
        self.enterContext(patch.object(upgrade.files, "ROOT", self.root))
        self.enterContext(patch.object(upgrade.auth, "ROOT", self.root))
        self.enterContext(
            patch.object(upgrade.auth, "RECORD", self.root / "frontend-upgrade.json")
        )
        self.enterContext(patch.object(upgrade.hosted, "scope"))
        self.dev = self.enterContext(
            patch.object(upgrade.hosted, "dev_health", return_value=200)
        )
        self.api_smoke = self.enterContext(patch.object(upgrade.auth, "api_smoke"))
        self.live = self.enterContext(patch.object(upgrade.auth, "verify_live"))
        self.enterContext(
            patch.object(
                upgrade.hosted,
                "candidate",
                side_effect=lambda: self.containers.get(
                    self.names.get(upgrade.hosted.WEB)
                ),
            )
        )
        self.enterContext(
            patch.object(upgrade.hosted, "inspect", side_effect=self.inspect)
        )
        self.docker = self.enterContext(
            patch.object(upgrade.hosted, "docker", side_effect=self.run_docker)
        )
        self.enterContext(
            patch.object(
                upgrade.hosted,
                "docker_json",
                return_value=[
                    {
                        "Labels": {upgrade.hosted.LABEL: upgrade.hosted.IDENTITY},
                        "Containers": {
                            "web": {"Name": upgrade.hosted.WEB},
                            "pg": {"Name": upgrade.hosted.PG},
                        },
                    }
                ],
            )
        )
        self.outside = {"protected": "old dev / PostgreSQL / nginx"}
        self.enterContext(
            patch.object(upgrade, "outside_snapshot", return_value=self.outside)
        )
        self.enterContext(
            patch.object(
                upgrade,
                "case_snapshot",
                return_value={
                    "sha256": "case-sha",
                    "scoring_mode": "weighted_percent",
                    "team_count": 1,
                },
            )
        )
        self.verify_runtime = self.enterContext(patch.object(upgrade, "verify_runtime"))
        self.migration = self.enterContext(
            patch.object(
                upgrade, "migrate", return_value={"plan": [list(upgrade.MIGRATION)]}
            )
        )
        self.smoke = self.enterContext(patch.object(upgrade, "smoke"))
        self.enterContext(patch.object(upgrade, "wait_for_web"))
        self.backup = self.enterContext(
            patch.object(
                upgrade.files,
                "backup_database",
                side_effect=lambda path: (path / "database.dump").write_bytes(
                    b"verified synthetic dump"
                ),
            )
        )
        self.enterContext(
            patch.object(
                upgrade.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=10 * 2**30),
            )
        )
        self.bundle = self.directory / "bundle"
        self.bundle.mkdir()
        for name in upgrade.HELPERS:
            if name == "overall_base.json":
                (self.bundle / name).write_text(json.dumps(self.base))
            else:
                shutil.copyfile(SOURCE / name, self.bundle / name)
        for name in upgrade.PATCH_FILES:
            target = self.bundle / "api" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("new " + name)
        for name, data in self.new.items():
            if data != self.old.get(name):
                target = self.bundle / "frontend" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        self.manifest = {
            "format": upgrade.IDENTITY,
            "backend_revision": self.base["backend_revision"],
            "frontend_revision": self.base["frontend_revision"],
            "base_backend_revision": self.base["base_backend_revision"],
            "base_frontend_revision": self.base["base_frontend_revision"],
            "tooling_revision": "3" * 40,
            "new_files": {name: self.hash(data) for name, data in self.new.items()},
            "files": {
                str(path.relative_to(self.bundle)): upgrade.hosted.digest(path)
                for path in self.bundle.rglob("*")
                if path.is_file()
            },
        }
        self.write_manifest()

    @staticmethod
    def hash(data):
        import hashlib

        return hashlib.sha256(data).hexdigest()

    def write_manifest(self):
        (self.bundle / "overall-manifest.json").write_text(json.dumps(self.manifest))

    def inspect(self, name):
        return self.containers[self.names.get(name, name)]

    def run_docker(self, *args, **kwargs):
        self.calls.append(args)
        result = SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[0] == "container" and args[1] == "inspect":
            return SimpleNamespace(
                returncode=0, stdout=json.dumps([self.inspect(args[2])])
            )
        if args[0] == "inspect":
            return SimpleNamespace(returncode=1, stdout="")
        if args[0] == "rename":
            self.names[args[2]] = self.names.pop(args[1])
        elif args[0] in ("stop", "start"):
            container = self.inspect(args[-1])
            container["State"]["Running"] = args[0] == "start"
            if args[0] == "start":
                container["State"]["StartedAt"] = "restored-start"
        elif args[0] == "run":
            self.assertIn("-d", args)
            container = deepcopy(self.before)
            container["Id"] = "4" * 64
            container["Config"]["Hostname"] = "new-host"
            container["Config"]["Image"] = self.before["Image"]
            for index, value in enumerate(args[:-1]):
                if value == "--label":
                    name, value = args[index + 1].split("=", 1)
                    container["Config"]["Labels"][name] = value
            container["HostConfig"]["Mounts"] = ["new"]
            container["Mounts"] = []
            for index, value in enumerate(args[:-1]):
                if value == "--mount":
                    parts = args[index + 1].split(",")
                    values = dict(part.split("=", 1) for part in parts if "=" in part)
                    container["Mounts"].append(
                        {
                            "Type": "bind",
                            "Source": values["src"],
                            "Destination": values["dst"],
                            "RW": "readonly" not in parts,
                        }
                    )
            container["State"] = {"Running": True, "StartedAt": "new-start"}
            self.containers[container["Id"]] = container
            self.names[upgrade.hosted.WEB] = container["Id"]
            result.stdout = container["Id"] + "\n"
        else:
            self.fail("Unexpected Docker operation: " + repr(args))
        return result

    def assert_data_preserved(self):
        self.assertEqual(
            (self.root / "data/case-sentinel").read_text(), "existing scores / team / PDF"
        )
        self.assertEqual(
            (self.root / "invite-upgrade.json").read_text(), "old invite record"
        )
        self.assertEqual((self.root / ".env").read_text(), "TEST=unchanged\n")
        self.assertEqual(self.route.read_text(), "unchanged routes")
        self.assertEqual(self.maps.read_text(), "unchanged maps")

    def test_check_is_read_only_for_code_frontend_state_and_migration(self):
        before = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        upgrade.check(self.bundle)
        after = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse(
            any(call[0] in ("run", "stop", "rename", "start") for call in self.calls)
        )
        self.assertFalse(self.migration.call_args.kwargs["apply"])

    def test_probe_reports_empty_plan_after_retained_schema(self):
        self.migration.return_value = {"plan": []}
        self.assertEqual(upgrade.check(self.bundle)[3], [])

    def test_runtime_fingerprint_rejects_changed_source_and_accepts_exact_target(self):
        with patch.object(
            upgrade, "runtime_fingerprint", return_value=self.base["runtime_hashes"]
        ):
            VERIFY_RUNTIME(self.before, updated=False)
        changed = {**self.base["runtime_hashes"], "partner_programs/models.py": "f" * 64}
        with patch.object(
            upgrade, "runtime_fingerprint", return_value=changed
        ), self.assertRaises(upgrade.hosted.Refused):
            VERIFY_RUNTIME(self.before, updated=False)
        updated = {**self.base["runtime_hashes"], **self.base["target_hashes"]}
        with patch.object(upgrade, "runtime_fingerprint", return_value=updated):
            VERIFY_RUNTIME(self.before, updated=True)

    def test_bundle_rejects_another_frontend_even_with_valid_file_hashes(self):
        self.manifest["new_files"]["index.html"] = "f" * 64
        self.manifest["files"]["frontend/index.html"] = "f" * 64
        self.write_manifest()
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.verify_bundle(self.bundle)

    def test_failure_journal_error_does_not_prevent_rollback(self):
        write = upgrade.hosted.private_write

        def fail_log(path, value):
            if path.name == "failure.txt":
                raise OSError("injected log write failure")
            return write(path, value)

        with patch.object(upgrade.hosted, "private_write", side_effect=fail_log):
            self.assert_smoke_failure_restores(RuntimeError("injected smoke failure"))

    def test_apply_reuses_image_env_data_and_publishes_index_last(self):
        writes = []
        copy = upgrade.files.copy_atomic

        def tracked(source, target, mode=0o644):
            if target.is_relative_to(self.root / "frontend"):
                writes.append(str(target.relative_to(self.root / "frontend")))
            return copy(source, target, mode)

        with patch.object(upgrade.files, "copy_atomic", side_effect=tracked):
            result = upgrade.apply(self.bundle)
        self.assertEqual(result["phase"], "active")
        self.assertEqual(writes[-1], "index.html")
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), self.new["index.html"]
        )
        self.assertEqual(
            (self.root / "frontend/main-old.js").read_bytes(), self.old["main-old.js"]
        )
        self.assertEqual(self.inspect(upgrade.hosted.WEB)["Image"], self.before["Image"])
        self.assertEqual(
            self.inspect(upgrade.hosted.WEB)["Config"]["Env"],
            ["TEST=unchanged", "OTHER=still"],
        )
        self.assert_data_preserved()
        self.assertEqual(
            [call.kwargs["apply"] for call in self.migration.call_args_list],
            [False, False, True],
        )
        self.assertTrue((Path(result["backup"]) / "database.dump").is_file())
        self.assertEqual(self.inspect(self.before["Id"])["State"]["Running"], False)

    def test_failed_migration_rolls_back_without_replacing_web_or_restoring_database(
        self,
    ):
        self.migration.side_effect = [
            {"plan": [list(upgrade.MIGRATION)]},
            None,
            RuntimeError("injected DDL failure"),
        ]
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.apply(self.bundle)
        record = upgrade.load_record()
        self.assertEqual(record["phase"], "rolled_back")
        self.assertEqual(self.inspect(upgrade.hosted.WEB)["Id"], self.before["Id"])
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), self.old["index.html"]
        )
        self.assert_data_preserved()
        self.assertFalse(any(call[0] in ("rename", "stop", "run") for call in self.calls))

    def assert_smoke_failure_restores(self, error):
        self.smoke.side_effect = error
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.apply(self.bundle)
        self.assertEqual(self.inspect(upgrade.hosted.WEB)["Id"], self.before["Id"])
        self.assertTrue(self.inspect(upgrade.hosted.WEB)["State"]["Running"])
        self.assertEqual(upgrade.load_record()["phase"], "rolled_back")
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), self.old["index.html"]
        )
        self.assert_data_preserved()

    def test_smoke_failure_restores_exact_old_web_and_keeps_schema(self):
        self.assert_smoke_failure_restores(RuntimeError("smoke failure"))

    def test_interrupt_restores_exact_old_web_and_keeps_schema(self):
        self.assert_smoke_failure_restores(KeyboardInterrupt())

    def test_publication_failure_restores_old_ui_without_deleting_new_chunks(self):
        def live(digest):
            if digest == self.manifest["new_files"]["index.html"]:
                raise RuntimeError("injected HTTPS failure")

        self.live.side_effect = live
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.apply(self.bundle)
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), self.old["index.html"]
        )
        self.assertTrue((self.root / "frontend/main-new.js").is_file())
        self.assertEqual(self.inspect(upgrade.hosted.WEB)["Id"], self.before["Id"])
        self.assert_data_preserved()

    def test_repeat_apply_does_not_redeploy_and_rollback_is_compatible_with_weights(
        self,
    ):
        upgrade.apply(self.bundle)
        self.calls.clear()
        self.assertEqual(upgrade.apply(self.bundle)["phase"], "active")
        self.assertEqual(self.calls, [])
        record = upgrade.load_record()
        result = upgrade.rollback(record)
        self.assertTrue(result["schema_retained"])
        self.assertFalse(result["database_restored"])
        self.assertEqual(upgrade.status()["phase"], "rolled_back")
        self.assertEqual(upgrade.rollback(upgrade.load_record())["phase"], "rolled_back")
        self.assert_data_preserved()

    def test_active_status_checks_overall_api_health(self):
        upgrade.apply(self.bundle)
        self.smoke.side_effect = upgrade.hosted.Refused("injected unhealthy overall API")
        self.calls.clear()
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.status()
        self.assertEqual(self.calls, [])

    def test_frontend_or_backup_drift_stops_rollback_before_container_mutation(self):
        upgrade.apply(self.bundle)
        record = upgrade.load_record()
        (Path(record["backup"]) / "frontend/index.html").write_bytes(b"unexpected backup")
        self.calls.clear()
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.rollback(record)
        self.assertFalse(
            any(call[0] in ("stop", "rename", "start") for call in self.calls)
        )

    def test_changed_old_overlay_or_wrong_frontend_prevents_check(self):
        source = Path(self.mounts[2]["Source"])
        source.write_text("unknown code")
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.check(self.bundle)
        self.migration.assert_not_called()

    def test_bundle_rejects_extra_files_bad_hash_and_wrong_target(self):
        (self.bundle / "extra.txt").write_text("unexpected")
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.verify_bundle(self.bundle)
        (self.bundle / "extra.txt").unlink()
        self.manifest["backend_revision"] = "a" * 40
        self.write_manifest()
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.verify_bundle(self.bundle)
        self.manifest["backend_revision"] = self.base["backend_revision"]
        self.manifest["files"]["frontend/index.html"] = "0" * 64
        self.write_manifest()
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.verify_bundle(self.bundle)

    def test_overlay_replaces_existing_destinations_once_and_preserves_invites(self):
        args = upgrade.overlay_args(self.before, self.root / "new")
        destinations = [
            value.split("dst=", 1)[1].split(",", 1)[0] for value in args[1::2]
        ]
        self.assertEqual(len(destinations), len(set(destinations)))
        self.assertIn("/procollab/users/white_label_candidates.py", destinations)
        self.assertEqual(destinations.count("/procollab/partner_programs/models.py"), 1)
        self.assertNotIn("/procollab/pilot-data", destinations)
        self.assertTrue(all(value.endswith(",readonly") for value in args[1::2]))

    def test_unique_env_order_is_semantically_equal_but_values_are_preserved(self):
        after = deepcopy(self.before)
        after["Config"]["Env"].reverse()
        upgrade.preserved_configuration(self.before, after)
        after["Config"]["Env"][0] = "OTHER=changed"
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.preserved_configuration(self.before, after)

    def test_duplicate_env_order_and_container_fingerprints_remain_strict(self):
        before = deepcopy(self.before)
        before["Config"]["Env"] = ["TEST=one", "TEST=two"]
        after = deepcopy(before)
        after["Config"]["Env"].reverse()
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.preserved_configuration(before, after)
        self.assertNotEqual(
            upgrade.auth.configuration_fingerprint(before),
            upgrade.auth.configuration_fingerprint(after),
        )
        after = deepcopy(self.before)
        after["Config"]["Env"].reverse()
        self.assertNotEqual(
            upgrade.auth.configuration_fingerprint(self.before),
            upgrade.auth.configuration_fingerprint(after),
        )

    def test_limits_and_data_destination_changes_are_detected(self):
        after = deepcopy(self.before)
        after["HostConfig"]["Memory"] //= 2
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.preserved_configuration(self.before, after)
        after = deepcopy(self.before)
        after["Mounts"][0]["Source"] = "/unknown"
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.verify_replacement_mounts(self.before, after, self.root / "new")

    def test_package_roundtrip_uses_production_unpacker_and_only_expected_files(self):
        frontend = self.directory / "build"
        frontend.mkdir()
        for name, data in self.new.items():
            target = frontend / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(data)
        with patch.object(packager, "tooling_revision", return_value="3" * 40):
            result = packager.package(
                self.bundle / "api", frontend, self.directory / "release"
            )
        destination = self.directory / "unpacked"
        unpacker.unpack(Path(result["archive"]), destination)
        recovered = destination / "procollab-pilot"
        upgrade.verify_bundle(recovered)
        self.assertEqual(result["api_files"], 11)
        self.assertEqual(result["changed_frontend_files"], 2)


class OverallMigrationGuardTests(unittest.TestCase):
    def execute(self, plan, *, apply=True, database=None):
        django = ModuleType("django")
        django.setup = MagicMock()
        db = ModuleType("django.db")
        db.connection = MagicMock()
        db.connection.alias = "default"
        db.connection.settings_dict = database or {
            "NAME": upgrade.hosted.DB_NAME,
            "USER": upgrade.hosted.DB_ROLE,
            "HOST": "db",
        }
        executor = MagicMock()
        executor.migration_plan.return_value = plan
        module = ModuleType("django.db.migrations.executor")
        module.MigrationExecutor = MagicMock(return_value=executor)
        apps = ModuleType("django.apps")
        apps.apps = MagicMock()
        permissions = ModuleType("django.contrib.auth.management")
        permissions.create_permissions = MagicMock()
        with patch.dict(
            sys.modules,
            {
                "django": django,
                "django.db": db,
                "django.db.migrations.executor": module,
                "django.apps": apps,
                "django.contrib.auth.management": permissions,
            },
        ):
            exec(upgrade.migration_script(apply), {})
        return executor, db.connection, permissions.create_permissions

    def plan(self, *, name="ProgramQuizOutcome", operation="CreateModel"):
        op = type(operation, (), {"name": name})()
        return [
            (
                SimpleNamespace(
                    app_label=upgrade.MIGRATION[0],
                    name=upgrade.MIGRATION[1],
                    operations=[op],
                ),
                False,
            )
        ]

    def test_only_new_table_migration_applies_and_creates_standard_permissions(self):
        executor, _, metadata = self.execute(self.plan())
        executor.migrate.assert_called_once()
        metadata.assert_called_once()

    def test_readonly_probe_and_empty_plan_are_safe(self):
        executor, connection, metadata = self.execute(self.plan(), apply=False)
        executor.migrate.assert_not_called()
        metadata.assert_not_called()
        self.assertIn(
            "SET default_transaction_read_only = on",
            [
                call.args[0]
                for call in connection.cursor.return_value.__enter__.return_value.execute.call_args_list
            ],
        )
        self.execute([])[0].migrate.assert_called_once()

    def test_other_reverse_or_destructive_operations_rejected(self):
        unrelated = self.plan()
        unrelated[0][0].app_label = "users"
        for plan in (
            unrelated,
            [(self.plan()[0][0], True)],
            self.plan(operation="RunPython"),
            self.plan(name="OtherModel"),
        ):
            with self.subTest(plan=plan), self.assertRaises(RuntimeError):
                self.execute(plan)

    def test_other_database_or_role_cannot_be_migrated(self):
        for change in (
            {"NAME": "production"},
            {"HOST": "5.188.81.217"},
            {"USER": "root"},
        ):
            database = {
                "NAME": upgrade.hosted.DB_NAME,
                "USER": upgrade.hosted.DB_ROLE,
                "HOST": "db",
                **change,
            }
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.execute(self.plan(), database=database)
