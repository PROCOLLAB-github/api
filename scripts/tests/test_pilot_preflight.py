"""Не запускаем новый стек при недостатке ресурсов или чужом занятом порте."""

import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[2] / "deploy" / "pilot"
spec = importlib.util.spec_from_file_location("pilot_preflight", SOURCE / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class PilotPreflightTests(unittest.TestCase):
    def check(self, disk_gib, memory_mib, busy=False, own_gateway=False):
        probe = MagicMock()
        if busy:
            probe.__enter__.return_value.bind.side_effect = OSError("occupied")

        def command(argv):
            if "--filter" in argv:
                return 0, "127.0.0.1:18081->80/tcp" if own_gateway else ""
            return 0, ""

        output = io.StringIO()
        with (
            patch.object(preflight.socket, "gethostbyname", return_value="5.188.81.217"),
            patch.object(preflight.socket, "socket", return_value=probe),
            patch.object(preflight.shutil, "which", return_value="/bin/tool"),
            patch.object(
                preflight.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=disk_gib * 2**30),
            ),
            patch.object(
                preflight.Path,
                "read_text",
                return_value=f"MemAvailable: {memory_mib * 1024} kB\n",
            ),
            patch.object(preflight, "run", side_effect=command),
            patch.object(preflight.sys, "stdout", output),
        ):
            result = preflight.main(check=True)
        return result, output.getvalue()

    def test_current_dev_resources_block_second_stack(self):
        result, output = self.check(disk_gib=6.2, memory_mib=2150)
        self.assertEqual(result, 1)
        self.assertIn("8 GiB", output)
        self.assertIn("2560 MiB", output)

    def test_foreign_port_blocks_but_own_gateway_is_allowed(self):
        self.assertEqual(self.check(12, 4096, busy=True)[0], 1)
        self.assertEqual(self.check(12, 4096, busy=True, own_gateway=True)[0], 0)

    def test_docker_inspects_local_socket_without_inherited_target(self):
        with (
            patch.dict(
                preflight.os.environ,
                {"DOCKER_HOST": "tcp://foreign:2375", "DOCKER_CONTEXT": "foreign"},
            ),
            patch.object(
                preflight.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=""),
            ) as run,
        ):
            preflight.run(["docker", "ps"])
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["docker", "--host=unix:///var/run/docker.sock", "ps"])
        self.assertNotIn("DOCKER_HOST", kwargs["env"])
        self.assertNotIn("DOCKER_CONTEXT", kwargs["env"])
