"""Изоляция dev и сохранность файлов при публикации/откате статики пилота."""

import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "deploy/pilot"
with patch.object(sys, "path", [str(SOURCE), *sys.path]):
    upgrade = importlib.import_module("upgrade_frontend")
    packager = importlib.import_module("package_frontend")
    unpacker = importlib.import_module("unpack_candidate")
REAL_SNAPSHOT = upgrade.protected_snapshot
REAL_HEALTH = upgrade.hosted.health


class PilotFrontendUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.root = self.directory / "pilot"
        self.root.mkdir()
        (self.root / "frontend").mkdir()
        (self.root / "backup").mkdir()
        (self.root / "access.txt").write_text("Пароль входа: test-gate\n")
        self.route = self.root / "routes.inc"
        self.maps = self.root / "maps.conf"
        self.route.write_text("pilot routes unchanged")
        self.maps.write_text("pilot maps unchanged")
        for name in (".env", "state.json", "backend.py", "database-sentinel"):
            (self.root / name).write_text("unchanged " + name)
        self.original = {
            "index.html": b"old index",
            "main-old.js": b"old chunk retained for open tabs",
            "assets/logo.svg": b"unchanged logo",
        }
        self.new = {
            "index.html": b'<meta content="white-label-pilot-v1"><meta content="noindex, nofollow">new index',
            "main-new.js": b"new chunk",
            "assets/logo.svg": b"unchanged logo",
        }
        for relative, data in self.original.items():
            destination = self.root / "frontend" / relative
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(data)
        self.enterContext(patch.object(upgrade, "ROOT", self.root))
        self.enterContext(
            patch.object(upgrade, "RECORD", self.root / "frontend-upgrade.json")
        )
        self.enterContext(
            patch.object(upgrade, "BASE_INDEX", self.digest(self.original["index.html"]))
        )
        self.enterContext(patch.object(upgrade.files, "ROOT", self.root))
        self.enterContext(patch.object(upgrade.hosted, "NEW", self.root))
        self.enterContext(patch.object(upgrade.hosted, "ROUTES", self.route))
        self.enterContext(patch.object(upgrade.hosted, "MAPS", self.maps))
        self.scope = self.enterContext(patch.object(upgrade.hosted, "scope"))
        self.dev = self.enterContext(patch.object(upgrade.hosted, "dev_health"))
        self.container = {
            "Id": "pilot-original-id",
            "Image": "original-image",
            "State": {"Running": True},
        }
        self.enterContext(
            patch.object(upgrade.hosted, "candidate", return_value=self.container)
        )
        self.state = {
            "phase": "active",
            "app_patch_revision": upgrade.BACKEND,
            "weights_revision": upgrade.BACKEND,
            "image_id": "original-image",
            "new_routes_sha256": upgrade.hosted.digest(self.route),
            "new_maps_sha256": upgrade.hosted.digest(self.maps),
        }
        self.enterContext(
            patch.object(upgrade.hosted, "state_read", return_value=self.state)
        )
        (self.root / "weights-upgrade.json").write_text(
            json.dumps(
                {
                    "identity": "hosted-v2-weights-upgrade",
                    "phase": "active",
                    "release": upgrade.BACKEND,
                    "candidate_id": self.container["Id"],
                }
            )
        )
        self.snapshot = {
            "containers": {"dev": ["dev-original-id"]},
            "files": {"nginx": "unchanged"},
        }
        self.snapshot_mock = self.enterContext(
            patch.object(upgrade, "protected_snapshot", return_value=self.snapshot)
        )
        self.health = self.enterContext(
            patch.object(upgrade.hosted, "health", side_effect=self.http)
        )
        self.docker_mutation = self.enterContext(
            patch.object(
                upgrade.hosted,
                "docker",
                side_effect=AssertionError("Docker command forbidden"),
            )
        )
        self.bundle = self.directory / "procollab-pilot"
        self.bundle.mkdir()
        for relative in upgrade.HELPERS:
            shutil.copyfile(SOURCE / relative, self.bundle / relative)
        for relative, data in self.new.items():
            if data != self.original.get(relative):
                destination = self.bundle / "frontend" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        self.manifest = {
            "format": upgrade.IDENTITY,
            "backend_revision": upgrade.BACKEND,
            "base_frontend_revision": upgrade.PREVIOUS,
            "frontend_revision": upgrade.REVISION,
            "base_files": {p: self.digest(b) for p, b in self.original.items()},
            "new_files": {p: self.digest(b) for p, b in self.new.items()},
            "files": {
                str(p.relative_to(self.bundle)): upgrade.hosted.digest(p)
                for p in self.bundle.rglob("*")
                if p.is_file()
            },
        }
        self.write_manifest()

    @staticmethod
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    def write_manifest(self):
        (self.bundle / "frontend-manifest.json").write_text(json.dumps(self.manifest))

    def http(self, url, **kwargs):
        if url.endswith("/backend/instance/"):
            return 200, {}, b'{"enabled":true}'
        if url.endswith("/backend/programs/1/registration/"):
            return 200, {}, b'{"account_mode":"email_password"}'
        self.assertEqual(url, upgrade.hosted.ORIGIN + "/")
        return 200, {}, (self.root / "frontend/index.html").read_bytes()

    def test_apply_changes_only_static_files_and_publishes_index_last(self):
        order = []
        original_copy = upgrade.files.copy_atomic

        def copy(source, destination, mode=0o644):
            if destination.is_relative_to(self.root / "frontend"):
                order.append(str(destination.relative_to(self.root / "frontend")))
            return original_copy(source, destination, mode)

        with patch.object(upgrade.files, "copy_atomic", side_effect=copy):
            result = upgrade.apply(self.bundle)
        self.assertEqual(result["phase"], "active")
        self.assertFalse(result["containers_restarted"])
        self.assertFalse(result["database_changed"])
        self.assertEqual(order, ["main-new.js", "index.html"])
        self.assertEqual(
            (self.root / "frontend/main-old.js").read_bytes(),
            self.original["main-old.js"],
        )
        self.assertEqual(
            (self.root / "frontend/main-new.js").stat().st_mode & 0o777, 0o644
        )
        for name in (".env", "state.json", "backend.py", "database-sentinel"):
            self.assertEqual((self.root / name).read_text(), "unchanged " + name)
        self.docker_mutation.assert_not_called()

    def test_unhealthy_dev_stops_before_any_backup_or_frontend_write(self):
        self.dev.side_effect = upgrade.hosted.Refused("dev unavailable")
        with self.assertRaisesRegex(upgrade.hosted.Refused, "dev unavailable"):
            upgrade.apply(self.bundle)
        self.assertFalse(upgrade.RECORD.exists())
        self.assertEqual(list((self.root / "backup").iterdir()), [])
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), self.original["index.html"]
        )

    def test_failed_postpublish_dev_check_restores_previous_index_without_restarts(self):
        self.dev.side_effect = [None, upgrade.hosted.Refused("dev unavailable")]
        with self.assertRaisesRegex(upgrade.hosted.Refused, "восстановлен"):
            upgrade.apply(self.bundle)
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), self.original["index.html"]
        )
        self.assertEqual(upgrade.load_record()["phase"], "rolled_back")
        self.assertTrue((self.root / "frontend/main-new.js").exists())
        self.docker_mutation.assert_not_called()

    def test_failed_https_verification_automatically_rolls_back(self):
        original_http = self.http
        failed = False

        def fail_new_index_once(url, **kwargs):
            nonlocal failed
            if url == upgrade.hosted.ORIGIN + "/" and not failed:
                failed = True
                return 502, {}, b"bad gateway"
            return original_http(url, **kwargs)

        self.health.side_effect = fail_new_index_once
        with self.assertRaisesRegex(upgrade.hosted.Refused, "восстановлен"):
            upgrade.apply(self.bundle)
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), self.original["index.html"]
        )

    def test_baseline_drift_prevents_overwriting_operator_changes(self):
        (self.root / "frontend/assets/logo.svg").write_bytes(b"operator logo")
        with self.assertRaisesRegex(upgrade.hosted.Refused, "изменен"):
            upgrade.apply(self.bundle)
        self.assertEqual(
            (self.root / "frontend/assets/logo.svg").read_bytes(), b"operator logo"
        )
        self.assertFalse(upgrade.RECORD.exists())

    def test_corrupt_or_extra_bundle_file_rejected(self):
        for name in ("frontend/main-new.js", "api.py"):
            with self.subTest(name=name):
                target = self.bundle / name
                before = target.read_bytes() if target.exists() else None
                target.write_bytes(b"corrupted")
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_bundle(self.bundle)
                if before is None:
                    target.unlink()
                else:
                    target.write_bytes(before)

    def test_forbidden_paths_and_internal_symlink_rejected(self):
        for name in (
            ".",
            "../dev/index.html",
            "/etc/nginx/nginx.conf",
            "x/../a",
            "x\\y",
            "x\ny",
        ):
            with self.subTest(name=name), self.assertRaises(upgrade.hosted.Refused):
                upgrade.relative_name(name)
        link = self.root / "frontend/alias"
        link.symlink_to(self.root / "frontend/assets", target_is_directory=True)
        with self.assertRaises(upgrade.hosted.Refused):
            upgrade.frontend_path("alias/logo.svg")

    def test_second_apply_only_checks_existing_release(self):
        upgrade.apply(self.bundle)
        backups = list((self.root / "backup").iterdir())
        with patch.object(
            upgrade.files, "copy_atomic", side_effect=AssertionError("No repeat write")
        ):
            self.assertEqual(upgrade.apply(self.bundle)["phase"], "active")
        self.assertEqual(list((self.root / "backup").iterdir()), backups)

    def test_manual_rollback_keeps_old_and_new_chunks_for_open_tabs(self):
        upgrade.apply(self.bundle)
        upgrade.rollback(upgrade.load_record())
        self.assertEqual(upgrade.status()["frontend_revision"], upgrade.PREVIOUS)
        self.assertTrue((self.root / "frontend/main-old.js").exists())
        self.assertTrue((self.root / "frontend/main-new.js").exists())

    def test_rollback_does_not_overwrite_new_external_edits(self):
        upgrade.apply(self.bundle)
        (self.root / "frontend/index.html").write_bytes(b"external edit")
        with self.assertRaisesRegex(upgrade.hosted.Refused, "изменен снаружи"):
            upgrade.rollback(upgrade.load_record())
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), b"external edit"
        )

    def test_corrupt_backup_stops_rollback_before_any_static_write(self):
        upgrade.apply(self.bundle)
        record = upgrade.load_record()
        (Path(record["backup"]) / "frontend/index.html").write_bytes(b"corrupt backup")
        with self.assertRaisesRegex(upgrade.hosted.Refused, "повреждена"):
            upgrade.rollback(record)
        self.assertEqual(
            (self.root / "frontend/index.html").read_bytes(), self.new["index.html"]
        )

    def test_frontend_package_has_only_changed_assets_and_safe_zip_envelope(self):
        frontend = self.directory / "compiled"
        frontend.mkdir()
        for relative, data in self.new.items():
            target = frontend / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        base = self.directory / "base.json"
        base.write_text(
            json.dumps(
                {
                    "api_revision": upgrade.BACKEND,
                    "files": {
                        "frontend/" + p: self.digest(b) for p, b in self.original.items()
                    },
                }
            )
        )
        meta = packager.package(frontend, base, self.directory / "package")
        unpacked = unpacker.unpack(Path(meta["archive"]), self.directory / "unpacked")
        manifest = upgrade.verify_bundle(unpacked)
        self.assertEqual(meta["changed_files"], 2)
        self.assertEqual(
            set(manifest["files"]),
            upgrade.HELPERS | {"frontend/index.html", "frontend/main-new.js"},
        )
        self.assertFalse((unpacked / "api").exists())
        self.assertFalse((unpacked / "frontend/assets/logo.svg").exists())

    def test_snapshot_detects_external_changes_without_exposing_container_secrets(self):
        from types import SimpleNamespace

        container = {
            "Id": "original-id",
            "Image": "original-image",
            "State": {"Running": True, "StartedAt": "original-start"},
            "Config": {"Env": ["PASSWORD=never-export-this"]},
            "HostConfig": {},
            "Mounts": [
                {"Type": "bind", "RW": False, "Source": str(self.root / "backend.py")}
            ],
        }
        with patch.object(
            upgrade.hosted, "inspect", return_value=container
        ), patch.object(
            upgrade.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=b"nginx original"),
        ) as nginx:
            first = REAL_SNAPSHOT()
            self.assertNotIn("never-export-this", json.dumps(first))
            nginx.assert_called_once_with(
                ["nginx", "-T"], capture_output=True, check=True
            )
            (self.root / "backend.py").write_text("changed backend")
            self.assertNotEqual(first, REAL_SNAPSHOT())
            (self.root / "backend.py").write_text("unchanged backend.py")
            container["State"]["StartedAt"] = "external restart"
            self.assertNotEqual(first, REAL_SNAPSHOT())

    def test_symlink_backup_is_rejected_before_writes(self):
        (self.root / "backup").rmdir()
        (self.root / "backup").symlink_to(
            self.root / "frontend", target_is_directory=True
        )
        with self.assertRaisesRegex(upgrade.hosted.Refused, "backup является ссылкой"):
            upgrade.apply(self.bundle)
        self.assertFalse(upgrade.RECORD.exists())

    def test_real_http_publication_retry_and_automatic_rollback_preserve_dev(self):
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from urllib.parse import urlsplit

        frontend = self.root / "frontend"
        fail_new_index = [False]

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(frontend), **kwargs)

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path in (
                    "/dev",
                    "/backend/instance/",
                    "/backend/programs/1/registration/",
                ):
                    body = {
                        "/dev": b"existing dev remains available",
                        "/backend/instance/": b'{"enabled":true}',
                        "/backend/programs/1/registration/": b'{"account_mode":"email_password"}',
                    }[self.path]
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(body)
                elif (
                    self.path == "/"
                    and fail_new_index[0]
                    and (frontend / "index.html").read_bytes().endswith(b"new index")
                ):
                    fail_new_index[0] = False
                    self.send_error(502)
                else:
                    super().do_GET()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        local = "http://127.0.0.1:" + str(server.server_port)

        def real_http(url, **kwargs):
            return REAL_HEALTH(local + urlsplit(url).path, **kwargs)

        def dev_health():
            code, _, body = REAL_HEALTH(local + "/dev")
            self.assertEqual((code, body), (200, b"existing dev remains available"))

        try:
            self.health.side_effect = real_http
            self.dev.side_effect = dev_health
            self.assertEqual(upgrade.apply(self.bundle)["phase"], "active")
            self.assertEqual(REAL_HEALTH(local + "/")[2], self.new["index.html"])
            upgrade.rollback(upgrade.load_record())
            fail_new_index[0] = True
            with self.assertRaisesRegex(upgrade.hosted.Refused, "восстановлен"):
                upgrade.apply(self.bundle)
            self.assertEqual(REAL_HEALTH(local + "/")[2], self.original["index.html"])
            self.assertEqual(upgrade.load_record()["phase"], "rolled_back")
            self.assertEqual(upgrade.status()["dev_http"], 200)
            self.docker_mutation.assert_not_called()
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
