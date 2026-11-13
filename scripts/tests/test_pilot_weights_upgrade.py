"""Границы source overlay, миграций и отката процентных весов пилота."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[2] / "deploy/pilot"
with patch.object(sys, "path", [str(SOURCE), *sys.path]):
    spec = importlib.util.spec_from_file_location(
        "pilot_weights_upgrade", SOURCE / "upgrade_weights.py"
    )
    upgrade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upgrade)


class PilotWeightsUpgradeTests(unittest.TestCase):
    def manifest(self):
        result = {"api/" + p: h for p, h in upgrade.BASE["protected"].items()}
        result.update({"api/" + p: "a" * 64 for p in upgrade.PATCH_FILES})
        return {"files": result}

    def test_only_known_current_code_and_unchanged_invites_profile_dependencies(self):
        hashes = {**upgrade.BASE["patches"], **upgrade.BASE["protected"]}
        result = upgrade.validate_backend(hashes, self.manifest())
        self.assertEqual(set(result), set(upgrade.PATCH_FILES))
        for name in (
            "project_rates/models.py",
            "project_rates/scoring.py",
            "users/views.py",
        ):
            with self.subTest(name=name), self.assertRaises(upgrade.hosted.Refused):
                upgrade.validate_backend({**hashes, name: "b" * 64}, self.manifest())
        for name in upgrade.BASE["protected"]:
            manifest = self.manifest()
            manifest["files"]["api/" + name] = "b" * 64
            with self.subTest(protected=name), self.assertRaises(upgrade.hosted.Refused):
                upgrade.validate_backend(hashes, manifest)

    def test_missing_patch_rejected(self):
        manifest = self.manifest()
        manifest["files"].pop("api/project_rates/scoring.py")
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.validate_backend(
                {**upgrade.BASE["patches"], **upgrade.BASE["protected"]}, manifest
            )

    def test_overlay_retains_invite_files_readonly_and_does_not_rebind_data(self):
        current = {
            "Mounts": [
                {
                    "Source": str(upgrade.ROOT / "data"),
                    "Destination": "/procollab/pilot-data",
                },
                {"Source": str(upgrade.ROOT / "logs"), "Destination": "/procollab/log"},
                *[
                    {"Source": "/known/" + name, "Destination": "/procollab/" + name}
                    for name in upgrade.files.PATCH_FILES
                ],
            ]
        }
        args = upgrade.overlay_args(current, Path("/known/weights"))
        self.assertTrue(all(value.endswith(",readonly") for value in args[1::2]))
        self.assertTrue(
            any(
                "dst=/procollab/users/white_label_candidates.py," in value
                for value in args
            )
        )
        self.assertTrue(
            any(
                "dst=/procollab/templates/partner_programs/admin/evaluation_criteria.html,"
                in value
                for value in args
            )
        )
        self.assertFalse(
            any("pilot-data" in value or "dst=/procollab/log," in value for value in args)
        )

    def run_migration(self, plan, *, apply=True):
        connection = MagicMock()
        connection.settings_dict = {
            "NAME": upgrade.hosted.DB_NAME,
            "USER": upgrade.hosted.DB_ROLE,
            "HOST": "db",
        }
        executor = MagicMock()
        executor.migration_plan.return_value = plan
        factory = MagicMock(return_value=executor)
        django = ModuleType("django")
        django.setup = MagicMock()
        db = ModuleType("django.db")
        db.connection = connection
        module = ModuleType("django.db.migrations.executor")
        module.MigrationExecutor = factory
        with patch.dict(
            sys.modules,
            {"django": django, "django.db": db, "django.db.migrations.executor": module},
        ):
            exec(upgrade.migration_script(apply=apply), {})
        return executor

    def migrations(self):
        operation = type("AddField", (), {})()
        return [
            (SimpleNamespace(app_label=app, name=name, operations=[operation]), False)
            for app, name in sorted(upgrade.MIGRATIONS)
        ]

    def test_only_two_additive_migrations_can_be_applied(self):
        executor = self.run_migration(self.migrations())
        executor.migrate.assert_called_once()

    def test_readonly_plan_does_not_execute_migrations_and_retry_accepts_empty_plan(self):
        self.run_migration(self.migrations(), apply=False).migrate.assert_not_called()
        self.run_migration([]).migrate.assert_called_once()

    def test_unrelated_reverse_and_destructive_migrations_rejected_before_write(self):
        unexpected = SimpleNamespace(app_label="users", name="unknown", operations=[])
        destructive = self.migrations()
        destructive[0][0].operations = [type("RemoveField", (), {})()]
        for plan in [
            self.migrations() + [(unexpected, False)],
            [(self.migrations()[0][0], True)],
            destructive,
        ]:
            with self.subTest(plan=plan), self.assertRaises(RuntimeError):
                self.run_migration(plan)

    def test_rollback_does_not_drop_schema_restore_database_or_overwrite_invite_record(
        self,
    ):
        record = {"phase": "active"}
        with patch.object(
            upgrade, "weighted_program_count", return_value=0
        ), patch.object(
            upgrade.files, "rollback", return_value={"phase": "rolled_back"}
        ) as restore:
            result = upgrade.rollback(record)
        restore.assert_called_once_with(record, record_writer=upgrade.save_record)
        self.assertTrue(result["schema_retained"])
        self.assertFalse(result["nginx_changed"])

    def test_rollback_refuses_to_reinterpret_active_percentage_scores_with_old_api(self):
        with patch.object(
            upgrade, "weighted_program_count", return_value=1
        ), patch.object(upgrade.files, "rollback") as restore:
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.rollback({"phase": "active"})
        restore.assert_not_called()

    def test_timeout_stops_only_owned_migrator_before_rollback(self):
        import json
        import subprocess

        migrator = {
            "Id": "owned-step",
            "Image": "image",
            "Config": {
                "Labels": {
                    upgrade.hosted.LABEL: upgrade.hosted.IDENTITY,
                    "io.procollab.pilot.weights.step": "weights-release",
                }
            },
        }
        response = SimpleNamespace(returncode=0, stdout=json.dumps([migrator]))
        with patch.object(
            upgrade.hosted,
            "docker",
            side_effect=[
                subprocess.TimeoutExpired("docker", 180),
                response,
                SimpleNamespace(returncode=0),
                SimpleNamespace(returncode=0),
            ],
        ) as docker:
            with self.assertRaises(subprocess.TimeoutExpired):
                upgrade.migrate(
                    {"Image": "image", "Mounts": []},
                    Path("/release/weights-release/backend"),
                    apply=True,
                    log=None,
                )
        self.assertEqual(
            docker.call_args_list[-2].args, ("stop", "--time", "5", "owned-step")
        )
        self.assertEqual(docker.call_args_list[-1].args, ("rm", "-f", "owned-step"))

    def test_changed_dev_or_nginx_is_reported_without_mutation(self):
        record = {"outside": {"original": True}}
        with patch.object(
            upgrade, "dev_snapshot", return_value={"other": True}
        ), patch.object(upgrade.hosted, "docker") as docker:
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.verify_outside(record)
        docker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
