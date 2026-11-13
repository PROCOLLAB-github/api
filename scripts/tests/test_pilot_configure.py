"""Границы пакета: секреты закрыты, повтор не меняет существующий пилот."""

import importlib.util
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "deploy" / "pilot"
spec = importlib.util.spec_from_file_location("pilot_configure", SOURCE / "configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class PilotConfigureTests(unittest.TestCase):
    def test_new_secrets_are_private_and_repeat_does_not_overwrite(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copy2(SOURCE / "nginx.conf.template", root)
            configure.configure(root)
            before = (root / ".env").read_bytes()
            for name in (".env", "nginx.conf", "access.htpasswd", "access.txt"):
                self.assertEqual(stat.S_IMODE((root / name).stat().st_mode), 0o600)
            for folder, mode in (
                ("data", 0o711),
                ("data/media", 0o755),
                ("data/static", 0o755),
                ("data/mail", 0o700),
                ("logs", 0o700),
            ):
                self.assertEqual(stat.S_IMODE((root / folder).stat().st_mode), mode)
            self.assertNotIn("@@GATE_TOKEN@@", (root / "nginx.conf").read_text())
            self.assertNotIn("WhiteLabel-demo-2026!", (root / ".env").read_text())
            with self.assertRaises(FileExistsError):
                configure.configure(root)
            self.assertEqual((root / ".env").read_bytes(), before)

    def test_external_credentials_and_non_https_origin_rejected(self):
        with TemporaryDirectory() as temp:
            for origin in (
                "http://pilot.procollab.ru",
                "https://user:secret@pilot.procollab.ru",
                "https://pilot.procollab.ru/path",
            ):
                with self.subTest(origin=origin), self.assertRaises(ValueError):
                    configure.configure(Path(temp), origin)
