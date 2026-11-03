import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import prod_backup as backup
import prod_preflight as preflight


class ProductionBackupTests(unittest.TestCase):
    def test_root_reads_app_repository_as_its_owner(self):
        owner = SimpleNamespace(st_uid=1001)
        accounts = SimpleNamespace(getpwuid=lambda uid: SimpleNamespace(pw_name="app"))
        with patch.object(
            preflight.REPO.__class__, "stat", return_value=owner
        ), patch.object(preflight.os, "geteuid", return_value=0, create=True), patch.dict(
            sys.modules, {"pwd": accounts}
        ), patch.object(
            preflight, "read", return_value="synthetic-sha"
        ) as read:
            self.assertEqual(
                preflight.repository_read("rev-parse", "HEAD"), "synthetic-sha"
            )
        self.assertEqual(read.call_args.args[0][:4], ["sudo", "-n", "-u", "app"])

    def test_archive_validation_child_sees_offset_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.dump"
            path.write_bytes(b"PGDMP" + b"x" * 16000)
            backup.validate_database_archive(
                path, [sys.executable, "-c", 'import os; assert os.read(0,5)==b"PGDMP"']
            )

    def test_invalid_archive_cannot_start_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.dump"
            path.write_bytes(b"invalid")
            with patch.object(backup.subprocess, "run") as run:
                with self.assertRaises(RuntimeError):
                    backup.validate_database_archive(path, ["pg_restore"])
            run.assert_not_called()

    def test_disk_reserve_stops_our_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            process = unittest.mock.MagicMock()
            process.poll.return_value = None
            with patch.object(
                backup.subprocess, "Popen", return_value=process
            ), patch.object(
                backup.shutil, "disk_usage", return_value=SimpleNamespace(free=0)
            ):
                with self.assertRaisesRegex(RuntimeError, "disk reserve"):
                    backup.guarded_archive(
                        ["synthetic-writer"], Path(directory) / "partial", stage="test"
                    )
            process.terminate.assert_called_once()

    def test_writer_errors_do_not_expose_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as raised:
                backup.guarded_archive(
                    [
                        sys.executable,
                        "-c",
                        'import sys; sys.stderr.write("authentication failed; password=PRIVATE-CANARY"); sys.exit(1)',
                    ],
                    Path(directory) / "partial",
                    stage="pg_dump",
                )
            self.assertIn("authentication_failed", str(raised.exception))
            self.assertNotIn("PRIVATE-CANARY", str(raised.exception))

    def test_client_must_match_server_major_exactly(self):
        result = SimpleNamespace(returncode=0, stdout=b"pg_dump (PostgreSQL) 16.1")
        with patch.object(Path, "is_file", return_value=True), patch.object(
            backup.shutil, "which", return_value=None
        ), patch.object(backup.subprocess, "run", return_value=result):
            self.assertIsNone(backup.native_clients(14))
            self.assertEqual(backup.native_clients(16)[1][-1], "--file=/dev/null")

    def test_image_archive_is_bound_to_running_image_id(self):
        config = b'{"synthetic":true}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.tar"
            with tarfile.open(path, "w") as archive:
                for name, content in [
                    ("manifest.json", json.dumps([{"Config": "config.json"}]).encode()),
                    ("config.json", config),
                ]:
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
            backup.validate_image_archive(
                path, "sha256:" + hashlib.sha256(config).hexdigest()
            )
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                backup.validate_image_archive(path, "sha256:" + "0" * 64)

    def test_cleanup_never_removes_other_containers(self):
        with patch.object(
            backup.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=b"different-run"),
        ) as run:
            backup.cleanup_helper("prod-dependency-pgdump-000000000001", "expected-run")
            self.assertEqual(run.call_count, 1)
        with patch.object(backup.subprocess, "run") as run:
            with self.assertRaises(RuntimeError):
                backup.cleanup_helper("prod-web-1", "expected-run")
            run.assert_not_called()

    def test_backup_path_guard_rejects_arbitrary_location(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            backup, "BACKUPS", Path(directory) / "unapproved"
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Unexpected production backup location"
            ):
                backup.prepare_folder("key", 0)


if __name__ == "__main__":
    unittest.main()
