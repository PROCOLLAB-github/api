"""Пакет содержит читаемые nginx assets и соответствует зафиксированной версии API."""

import importlib.util
import json
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "deploy" / "pilot"
spec = importlib.util.spec_from_file_location("pilot_package", SOURCE / "package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PilotPackageTests(unittest.TestCase):
    def prepare(self, root):
        api, frontend = root / "api", root / "frontend"
        (api / "procollab").mkdir(parents=True)
        (api / "procollab/settings_pilot.py").write_text("# synthetic profile\n")
        frontend.mkdir(mode=0o700)
        (frontend / "index.html").write_text("<meta content='white-label-pilot-v1'>")
        (frontend / "index.html").chmod(0o600)
        for args in (
            ["init", "-q"],
            ["add", "."],
            [
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.name=Pilot Test",
                "-c",
                "user.email=pilot@example.test",
                "commit",
                "-qm",
                "synthetic fixture",
            ],
        ):
            subprocess.run(["git", *args], cwd=api, check=True, capture_output=True)
        (api / ".env").write_text("PRIVATE=must-not-be-packaged\n")
        return api, frontend

    def test_public_assets_readable_and_untracked_secrets_excluded(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            api, frontend = self.prepare(root)
            target = root / "bundle"
            archive = package.package(api, frontend, target)
            self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((target / "frontend").stat().st_mode), 0o755)
            self.assertEqual(
                stat.S_IMODE((target / "frontend/index.html").stat().st_mode), 0o644
            )
            self.assertFalse((target / "api/.env").exists())
            manifest = json.loads((target / "manifest.json").read_text())
            self.assertIn(
                "procollab/settings_pilot.py",
                [name.removeprefix("api/") for name in manifest["files"]],
            )
            self.assertEqual(len(manifest["api_revision"]), 40)
            self.assertIn("upgrade_weights.py", manifest["files"])
            self.assertIn("weights_base.json", manifest["files"])

    def test_regular_frontend_and_dirty_api_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            api, frontend = self.prepare(root)
            (frontend / "index.html").write_text("ordinary build")
            with self.assertRaises(ValueError):
                package.package(api, frontend, root / "regular")
            (frontend / "index.html").write_text("white-label-pilot-v1")
            (api / "procollab/settings_pilot.py").write_text("uncommitted changes")
            with self.assertRaises(ValueError):
                package.package(api, frontend, root / "dirty")
