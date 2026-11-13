"""ZIP/TAR загрузки не может перезаписать существующие или внешние файлы."""

import importlib.util
import io
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[2] / "deploy/pilot/unpack_candidate.py"
spec = importlib.util.spec_from_file_location("pilot_unpack", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(path, name, link=False):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        entry = tarfile.TarInfo(name)
        entry.mode = 0o644
        if link:
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            archive.addfile(entry)
        else:
            payload = b"synthetic public asset"
            entry.size = len(payload)
            archive.addfile(entry, io.BytesIO(payload))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("procollab-pilot.tar.gz", buffer.getvalue())


class UnpackPilotTests(unittest.TestCase):
    def test_new_source_directory_and_repeat_guard(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root / "bundle.zip", "procollab-pilot/frontend/index.html")
            output = module.unpack(root / "bundle.zip", root / "unpacked")
            self.assertEqual(
                (output / "frontend/index.html").read_bytes(), b"synthetic public asset"
            )
            with self.assertRaises(FileExistsError):
                module.unpack(root / "bundle.zip", root / "unpacked")

    def test_traversal_and_symlink_rejected(self):
        for name, link in [
            ("procollab-pilot/../../outside.txt", False),
            ("procollab-pilot/key", True),
        ]:
            with self.subTest(name=name), TemporaryDirectory() as temp:
                root = Path(temp)
                fixture(root / "bundle.zip", name, link)
                with self.assertRaises(ValueError):
                    module.unpack(root / "bundle.zip", root / "new")
                self.assertFalse((root / "outside.txt").exists())
