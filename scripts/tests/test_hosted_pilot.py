"""Защита dev: чужой host/network, старые DB/роли и ошибочный nginx запрещены."""

import glob
import hashlib
import importlib.util
import json
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "deploy/pilot"
with patch.object(sys, "path", [str(SOURCE), *sys.path]):
    spec = importlib.util.spec_from_file_location("hosted_pilot", SOURCE / "hosted.py")
    hosted = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hosted)


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class HostedPilotGuards(unittest.TestCase):
    def test_dev_guard_does_not_require_react_containers(self):
        containers = {
            name: {"State": {"Running": True}}
            for name in ("api-web-1", "api-redis-1", "api_celery")
        }
        with (
            patch.object(
                hosted, "inspect", side_effect=containers.__getitem__
            ) as inspect,
            patch.object(hosted, "health", return_value=(200, {}, b"")) as health,
        ):
            self.assertEqual(hosted.dev_health(), 200)
        self.assertEqual(
            {call.args[0] for call in inspect.call_args_list}, set(containers)
        )
        health.assert_called_once_with("https://dev.procollab.ru/")

    def test_dev_guard_still_refuses_stopped_or_unhealthy_main_services(self):
        names = ("api-web-1", "api-redis-1", "api_celery")
        for name in names:
            for bad_state in (
                {"Running": False},
                {"Running": True, "Health": {"Status": "unhealthy"}},
            ):
                with self.subTest(name=name, state=bad_state):
                    containers = {other: {"State": {"Running": True}} for other in names}
                    containers[name] = {"State": bad_state}
                    with (
                        patch.object(
                            hosted, "inspect", side_effect=containers.__getitem__
                        ),
                        patch.object(hosted, "health") as health,
                    ):
                        with self.assertRaisesRegex(hosted.Refused, name):
                            hosted.dev_health()
                    health.assert_not_called()

    def test_dev_guard_still_refuses_failed_public_http(self):
        with (
            patch.object(hosted, "inspect", return_value={"State": {"Running": True}}),
            patch.object(hosted, "health", return_value=(503, {}, b"")),
        ):
            with self.assertRaises(hosted.Refused):
                hosted.dev_health()

    def test_maps_use_existing_sites_enabled_http_include(self):
        config = """events { worker_connections 1024; }
http {
    include       /etc/nginx/mime.types;
    include /etc/nginx/sites-enabled/*;
}"""
        hosted.validate_maps_include(config)
        self.assertEqual(hosted.MAPS.parent, Path("/etc/nginx/sites-enabled"))
        self.assertEqual(
            hosted.http_includes(config),
            ["/etc/nginx/mime.types", "/etc/nginx/sites-enabled/*"],
        )
        hosted.validate_maps_include(
            'http { include "/etc/nginx/sites-enabled/*.conf" ; }'
        )

    def test_comment_or_wrong_context_does_not_enable_maps(self):
        for config in (
            "# http { include /etc/nginx/sites-enabled/*; }",
            "stream { include /etc/nginx/sites-enabled/*; }",
            "http { server { include /etc/nginx/sites-enabled/*; } }",
            'http { log_format test "include /etc/nginx/sites-enabled/*;"; }',
        ):
            with self.subTest(config=config), self.assertRaises(hosted.Refused):
                hosted.validate_maps_include(config)

    def test_compiled_nginx_user_when_user_directive_is_omitted(self):
        with (
            patch.object(
                hosted.subprocess,
                "run",
                return_value=SimpleNamespace(
                    stdout="",
                    stderr="configure arguments: --user=www-data --group=www-data",
                ),
            ),
            patch.object(hosted.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=33)),
        ):
            self.assertEqual(hosted.nginx_group("events {} http {}"), 33)

    def test_atomic_write_hides_temporary_nginx_config(self):
        with TemporaryDirectory() as temp:
            destination = Path(temp) / "pilot.conf"
            replace = hosted.os.replace
            seen = []

            def commit(source, target):
                seen.append(source.name)
                self.assertEqual(glob.glob(str(Path(temp) / "*")), [])
                replace(source, target)

            with patch.object(hosted.os, "replace", side_effect=commit):
                hosted.private_write(destination, "map config")
            self.assertTrue(seen[0].startswith("."))
            self.assertEqual(destination.read_text(), "map config")

    def test_other_host_refused_before_docker_inspection(self):
        with (
            patch.object(hosted.os, "geteuid", return_value=0),
            patch.object(
                hosted.socket, "gethostname", return_value="procollab-production"
            ),
            patch.object(hosted, "inspect") as inspect,
        ):
            with self.assertRaises(hosted.Refused):
                hosted.scope()
        inspect.assert_not_called()

    def test_initialization_sql_targets_only_new_database_and_non_superuser(self):
        with self.assertRaises(hosted.Refused):
            hosted.database_sql(
                {"DATABASE_NAME": "white_label_pilot", "DATABASE_USER": hosted.DB_ROLE}
            )
        statement = hosted.database_sql(
            {
                "DATABASE_NAME": hosted.DB_NAME,
                "DATABASE_USER": hosted.DB_ROLE,
                "DATABASE_PASSWORD": "synthetic-password",
            }
        )
        self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE", statement)
        self.assertIn('ALTER DATABASE "procollab_white_label_pilot_v2"', statement)
        self.assertNotIn('"white_label_pilot"', statement)
        self.assertNotIn("ALTER ROLE", statement)

    def test_low_memory_stops_before_import_or_start(self):
        runtime = SimpleNamespace(
            info={"image_size_bytes": 2**30, "architecture": "amd64"}
        )
        with (
            patch.object(hosted, "scope", return_value={}),
            patch.object(hosted, "candidate", return_value=None),
            patch.object(
                hosted,
                "docker_json",
                return_value={
                    "Driver": "overlay2",
                    "DockerRootDir": "/tmp",
                    "Architecture": "amd64",
                },
            ),
            patch.object(hosted, "docker", return_value=SimpleNamespace(returncode=1)),
            patch.object(hosted.socket, "socket"),
            patch.object(
                hosted.Path, "read_text", return_value="MemAvailable: 500000 kB\n"
            ),
            patch.object(hosted, "existing_image") as image,
        ):
            with self.assertRaises(hosted.Refused):
                hosted.readiness(runtime)
        image.assert_not_called()

    def test_existing_network_with_dev_member_is_refused(self):
        with (
            patch.object(
                hosted,
                "docker",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        [
                            {
                                "Labels": {hosted.LABEL: hosted.IDENTITY},
                                "Containers": {"x": {"Name": "api-web-1"}},
                            }
                        ]
                    ),
                ),
            ),
            patch.object(hosted, "environment") as env,
        ):
            with self.assertRaises(hosted.Refused):
                hosted.prepare_database()
        env.assert_not_called()

    def test_mismatched_runtime_and_source_are_refused(self):
        with patch.object(
            hosted, "verify_bundle", return_value={"api_revision": "a" * 40}
        ):
            with self.assertRaises(hosted.Refused):
                hosted.verify_compatibility(
                    Path("unused"), SimpleNamespace(info={"api_revision": "b" * 40})
                )

    def test_symlink_outside_new_directory_is_refused(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "new"
            root.mkdir()
            outside = Path(temp) / "dev"
            outside.mkdir()
            (root / "data").symlink_to(outside, target_is_directory=True)
            with patch.object(hosted, "NEW", root):
                with self.assertRaises(hosted.Refused):
                    hosted.owned_path(root / "data/media")
            self.assertEqual(list(outside.iterdir()), [])

    def test_failed_preflight_creates_no_new_files_or_database(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "new"
            with (
                patch.object(hosted, "NEW", root),
                patch.object(
                    hosted,
                    "verify_compatibility",
                    return_value={"api_revision": "a" * 40},
                ),
                patch.object(
                    hosted, "readiness", side_effect=hosted.Refused("low resources")
                ),
                patch.object(hosted, "prepare_database") as sql,
            ):
                with self.assertRaises(hosted.Refused):
                    hosted.stage(Path(temp), object())
            self.assertFalse(root.exists())
            sql.assert_not_called()

    def test_rollback_preserves_files_changed_by_another_operator(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            routes = root / "routes.inc"
            maps = root / "maps.conf"
            routes.write_text("new routes")
            maps.write_text("foreign change")
            state = {
                "new_routes_sha256": sha("new routes"),
                "original_routes_sha256": sha("old routes"),
                "new_maps_sha256": sha("new maps"),
            }
            with patch.object(hosted, "ROUTES", routes), patch.object(
                hosted, "MAPS", maps
            ):
                with self.assertRaises(hosted.Refused):
                    hosted.rollback_files(state)
            self.assertEqual(routes.read_text(), "new routes")
            self.assertEqual(maps.read_text(), "foreign change")

    def test_nginx_failure_restores_only_pilot_routes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "backup").mkdir()
            routes = root / "routes.inc"
            maps = root / "maps.conf"
            routes.write_text("old routes")
            (root / "backup/routes.inc").write_text("old routes")
            dev = root / "dev.conf"
            dev.write_text("untouched dev")
            state = {
                "identity": hosted.IDENTITY,
                "phase": "staged",
                "original_routes_sha256": sha("old routes"),
                "image_id": "sha256:test",
                "gate_token": "a" * 32,
            }
            count = 0

            def nginx(argv, **kwargs):
                nonlocal count
                count += 1
                if count == 1:
                    raise subprocess.CalledProcessError(1, argv)
                return subprocess.CompletedProcess(argv, 0)

            with (
                patch.object(hosted, "NEW", root),
                patch.object(hosted, "ROUTES", routes),
                patch.object(hosted, "MAPS", maps),
                patch.object(hosted, "scope"),
                patch.object(hosted, "state_read", return_value=state),
                patch.object(
                    hosted,
                    "candidate",
                    return_value={"State": {"Running": True}, "Image": "sha256:test"},
                ),
                patch.object(hosted, "candidate_health"),
                patch.object(hosted, "dev_health", return_value=200),
                patch.object(hosted.subprocess, "run", side_effect=nginx),
            ):
                with self.assertRaises(hosted.Refused):
                    hosted.switch()
            self.assertEqual(routes.read_text(), "old routes")
            self.assertFalse(maps.exists())
            self.assertEqual(dev.read_text(), "untouched dev")
            self.assertEqual(
                json.loads((root / "state.json").read_text())["phase"], "rolled_back"
            )
