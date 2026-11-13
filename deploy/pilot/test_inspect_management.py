from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import inspect_management as probe


class ManagementInspectionTests(unittest.TestCase):
    def before(self):
        return {
            "containers": {"api-web-1": ["id", "image", "start", "fingerprint"]},
            "files": {"/opt/pilot/.env": "old-hash"},
            "nginx": "nginx-hash",
        }

    def test_equal_snapshots_have_no_changes(self):
        result = probe.snapshot_changes(self.before(), self.before())
        self.assertEqual(result, {"containers": [], "files": [], "nginx_changed": False})

    def test_reports_exact_container_fields_without_values(self):
        after = deepcopy(self.before())
        after["containers"]["api-web-1"][2] = "different-start"
        after["containers"]["api-web-1"][3] = "private-fingerprint-value"
        result = probe.snapshot_changes(self.before(), after)
        self.assertEqual(
            result["containers"],
            [{"name": "api-web-1", "changed": ["started_at", "configuration_hash"]}],
        )
        self.assertNotIn("private-fingerprint-value", repr(result))
        self.assertNotIn("different-start", repr(result))

    def test_reports_only_file_paths_not_values_and_separates_nginx(self):
        after = deepcopy(self.before())
        after["files"]["/opt/pilot/.env"] = "private-config-value"
        after["nginx"] = "different-nginx"
        result = probe.snapshot_changes(self.before(), after)
        self.assertEqual(result["files"], ["/opt/pilot/.env"])
        self.assertTrue(result["nginx_changed"])
        self.assertNotIn("private-config-value", repr(result))

    def test_added_and_missing_resources_are_not_silently_skipped(self):
        after = {
            "containers": {"another": ["id", "image", "start", "fp"]},
            "files": {},
            "nginx": "nginx-hash",
        }
        result = probe.snapshot_changes(self.before(), after)
        self.assertEqual(
            [item["name"] for item in result["containers"]], ["another", "api-web-1"]
        )
        self.assertEqual(result["files"], ["/opt/pilot/.env"])

    def test_import_requires_exact_verified_helper_bytes(self):
        with TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            helper = bundle / "helper.py"
            helper.write_bytes(b"known bytes")
            import hashlib

            with patch.object(
                probe,
                "BUNDLE_HASHES",
                {"helper.py": hashlib.sha256(helper.read_bytes()).hexdigest()},
            ):
                probe.check_bundle(bundle)
                helper.write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    probe.check_bundle(bundle)

    def test_symlink_helper_is_rejected(self):
        with TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            (bundle / "original").write_bytes(b"known bytes")
            (bundle / "helper.py").symlink_to(bundle / "original")
            with patch.object(probe, "BUNDLE_HASHES", {"helper.py": "0" * 64}):
                with self.assertRaises(ValueError):
                    probe.check_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
