from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import upgrade_admin_form as upgrade


class AdminFormUpgradeTests(unittest.TestCase):
    def test_package_identity_file_mutation_extra_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = b"# isolated admin patch\n"
            digest = lambda value: hashlib.sha256(value).hexdigest()  # noqa: E731
            base = {
                "backend_revision": "1" * 40,
                "base_backend_revision": "2" * 40,
                "frontend_revision": "3" * 40,
                "target_hash": digest(source),
            }
            target = root / "api/partner_programs/admin.py"
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            (root / "admin_form_base.json").write_text(json.dumps(base))
            manifest = {
                "format": upgrade.IDENTITY,
                "tooling_revision": "f" * 40,
                **{k: v for k, v in base.items() if k.endswith("revision")},
                "files": {
                    str(p.relative_to(root)): digest(p.read_bytes())
                    for p in root.rglob("*")
                    if p.is_file()
                },
            }
            (root / "admin-form-manifest.json").write_text(json.dumps(manifest))
            with patch.object(upgrade, "BASE", base), patch.object(
                upgrade, "HELPERS", {"admin_form_base.json"}
            ):
                self.assertEqual(upgrade.verify_bundle(root), manifest)
                target.write_bytes(b"changed")
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_bundle(root)
                target.write_bytes(source)
                extra = root / "unexpected"
                extra.write_bytes(b"extra")
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_bundle(root)
                extra.unlink()
                extra.symlink_to(target)
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_bundle(root)

    def test_current_dev_or_expert_history_changes_prevent_any_followup(self):
        original = {
            "containers": {"api-web-1": "known"},
            "files": {"expert-upgrade.json": "known"},
        }
        record = {"old_container_id": "old", "outside": original}
        for part in ("containers", "files"):
            changed = deepcopy(original)
            changed[part]["unexpected"] = "modified"
            with self.subTest(part=part), patch.object(
                upgrade.hosted, "inspect"
            ), patch.object(
                upgrade, "outside_snapshot", return_value=changed
            ), patch.object(
                upgrade.hosted, "dev_health"
            ) as health:
                with self.assertRaises(upgrade.hosted.Refused):
                    upgrade.verify_outside(record)
                health.assert_not_called()


if __name__ == "__main__":
    unittest.main()
