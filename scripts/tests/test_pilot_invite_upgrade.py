"""Source-only pilot update refuses foreign code and preserves outside edits."""

import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "deploy/pilot"
with patch.object(sys, "path", [str(SOURCE), *sys.path]):
    spec = importlib.util.spec_from_file_location(
        "pilot_invite_upgrade", SOURCE / "upgrade_invites.py"
    )
    upgrade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upgrade)


class PilotInviteUpgradeTests(unittest.TestCase):
    def manifest(self):
        files = {"api/" + name: value for name, value in upgrade.BASE_HASHES.items()}
        for name in upgrade.PATCH_FILES:
            files["api/" + name] = "a" * 64
        return {"files": files}

    def test_only_known_base_code_and_dependencies_are_accepted(self):
        self.assertEqual(
            set(upgrade.validate_backend(upgrade.BASE_HASHES, self.manifest())),
            set(upgrade.PATCH_FILES),
        )
        altered = {**upgrade.BASE_HASHES, "users/views.py": "b" * 64}
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.validate_backend(altered, self.manifest())
        altered = {**upgrade.BASE_HASHES, "users/white_label_candidates.py": "b" * 64}
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.validate_backend(altered, self.manifest())
        bundle = self.manifest()
        bundle["files"]["api/poetry.lock"] = "b" * 64
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.validate_backend(upgrade.BASE_HASHES, bundle)

    def test_frontend_cannot_escape_into_data_or_follow_external_links(self):
        with TemporaryDirectory() as directory, patch.object(
            upgrade, "ROOT", Path(directory)
        ):
            root = Path(directory)
            (root / "frontend").mkdir()
            (root / "data").mkdir()
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.frontend_path("../data/upload.pdf")
            (root / "frontend/link").symlink_to(root / "data", target_is_directory=True)
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.frontend_path("link/upload.pdf")

    def test_foreign_frontend_changes_stop_rollback_before_container_operations(self):
        with TemporaryDirectory() as directory, patch.object(
            upgrade, "ROOT", Path(directory)
        ):
            root = Path(directory)
            (root / "frontend").mkdir()
            (root / "frontend/index.html").write_text("operator change")
            record = {
                "phase": "active",
                "backup": str(root / "backup"),
                "frontend": {"index.html": {"before": "a" * 64, "after": "b" * 64}},
            }
            with patch.object(upgrade.hosted, "docker") as docker:
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.rollback(record)
            docker.assert_not_called()

    def test_changed_container_cannot_be_stopped_by_rollback(self):
        record = {
            "phase": "active",
            "backup": "/unused",
            "frontend": {},
            "old_container_id": "old",
            "release": "a" * 40,
            "candidate_id": "expected",
        }
        container = {
            "Id": "foreign",
            "Config": {
                "Labels": {
                    upgrade.REVISION_LABEL: "a" * 40,
                    upgrade.hosted.LABEL: upgrade.hosted.IDENTITY,
                }
            },
            "State": {"Running": True},
        }
        with patch.object(
            upgrade.hosted,
            "docker",
            return_value=SimpleNamespace(returncode=0, stdout=json.dumps([container])),
        ) as docker:
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.rollback(record)
        self.assertEqual(docker.call_count, 1)

    def test_atomic_frontend_write_never_publishes_partial_index(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "new.html"
            source.write_bytes(b"complete new index")
            target = root / "index.html"
            target.write_bytes(b"old index")
            replace = upgrade.os.replace

            def commit(temporary, destination):
                self.assertEqual(target.read_bytes(), b"old index")
                self.assertEqual(temporary.read_bytes(), source.read_bytes())
                replace(temporary, destination)

            with patch.object(upgrade.os, "replace", side_effect=commit):
                upgrade.copy_atomic(source, target)
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).digest(),
                hashlib.sha256(target.read_bytes()).digest(),
            )

    def test_missing_frontend_backup_stops_rollback_before_container_operations(self):
        with TemporaryDirectory() as directory, patch.object(
            upgrade, "ROOT", Path(directory)
        ):
            root = Path(directory)
            (root / "frontend").mkdir()
            (root / "frontend/index.html").write_bytes(b"new index")
            record = {
                "phase": "active",
                "backup": str(root / "backup"),
                "frontend": {
                    "index.html": {
                        "before": hashlib.sha256(b"old index").hexdigest(),
                        "after": hashlib.sha256(b"new index").hexdigest(),
                    }
                },
            }
            with patch.object(upgrade.hosted, "docker") as docker:
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.rollback(record)
            docker.assert_not_called()

    def test_changed_saved_container_is_detected_before_stopping_active_web(self):
        record = {
            "phase": "active",
            "backup": "/unused",
            "frontend": {},
            "old_container_id": "old",
            "old_name": "saved-old",
            "release": "a" * 40,
            "candidate_id": "new",
            "previous_state": {"image_id": "image"},
        }
        current = {
            "Id": "new",
            "Config": {
                "Labels": {
                    upgrade.REVISION_LABEL: "a" * 40,
                    upgrade.hosted.LABEL: upgrade.hosted.IDENTITY,
                }
            },
            "State": {"Running": True},
        }
        with patch.object(
            upgrade.hosted,
            "docker",
            return_value=SimpleNamespace(returncode=0, stdout=json.dumps([current])),
        ) as docker, patch.object(
            upgrade.hosted, "inspect", return_value={"Id": "foreign"}
        ):
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.rollback(record)
        self.assertEqual(docker.call_count, 1)

    def test_new_public_asset_directories_are_readable_under_private_umask(self):
        import os
        import stat

        with TemporaryDirectory() as directory, patch.object(
            upgrade, "ROOT", Path(directory)
        ):
            root = Path(directory)
            source = root / "asset"
            source.write_bytes(b"public asset")
            target = root / "frontend/assets/new/icon.svg"
            previous = os.umask(0o077)
            try:
                upgrade.copy_atomic(source, target)
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)

    def test_rollback_can_restore_old_web_after_new_container_fails_to_start(self):
        record = {
            "phase": "prepared",
            "backup": "/unused",
            "frontend": {},
            "old_container_id": "old",
            "old_name": "old-backup",
            "release": "a" * 40,
            "candidate_id": "new",
            "previous_state": {"image_id": "image"},
        }
        labels = {
            upgrade.REVISION_LABEL: "a" * 40,
            upgrade.hosted.LABEL: upgrade.hosted.IDENTITY,
        }
        failed = {"Id": "new", "Config": {"Labels": labels}, "State": {"Running": False}}
        old = {
            "Id": "old",
            "Image": "image",
            "Config": {"Labels": labels},
            "State": {"Running": False},
        }

        def docker(*args, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([failed])
                if args[:2] == ("container", "inspect")
                else "",
            )

        with patch.object(
            upgrade.hosted, "docker", side_effect=docker
        ) as calls, patch.object(
            upgrade.hosted, "inspect", return_value=old
        ), patch.object(
            upgrade.hosted, "state_write"
        ) as state, patch.object(
            upgrade, "save_record"
        ), patch.object(
            upgrade.hosted, "dev_health", return_value=200
        ):
            self.assertEqual(upgrade.rollback(record)["phase"], "rolled_back")
        self.assertFalse(any(call.args[0] == "stop" for call in calls.call_args_list))
        self.assertTrue(
            any(
                call.args == ("start", upgrade.hosted.WEB)
                for call in calls.call_args_list
            )
        )
        state.assert_called_once_with(record["previous_state"])


if __name__ == "__main__":
    unittest.main()
