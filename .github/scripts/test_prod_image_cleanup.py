from copy import deepcopy
import unittest
from unittest.mock import patch

import prod_image_cleanup as cleanup


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.prefix, self.tag = next(iter(cleanup.CANDIDATES.items()))
        self.image = {
            "Id": "sha256:" + self.prefix + "0" * 52,
            "Created": "2024-11-01T00:00:00.000000000Z",
            "RepoTags": [self.tag],
        }

    def test_only_reviewed_unused_old_image_passes(self):
        self.assertEqual(
            cleanup.validate_candidate(self.prefix, self.tag, self.image, set()),
            self.image["Id"],
        )

    def test_image_used_by_any_container_is_protected(self):
        with self.assertRaises(RuntimeError):
            cleanup.validate_candidate(
                self.prefix, self.tag, self.image, {self.image["Id"]}
            )

    def test_nanoseconds_preserve_cutoff_check(self):
        self.image["Created"] = "2026-05-02T23:59:59.999999999Z"
        self.assertEqual(
            cleanup.validate_candidate(self.prefix, self.tag, self.image, set()),
            self.image["Id"],
        )
        self.image["Created"] = "2026-05-03T00:00:00.000000001Z"
        with self.assertRaises(RuntimeError):
            cleanup.validate_candidate(self.prefix, self.tag, self.image, set())

    def test_tag_identity_age_or_new_reference_changes_block_removal(self):
        for key, value in (
            ("Id", "sha256:" + "f" * 64),
            ("Created", "2026-10-01T00:00:00Z"),
            ("RepoTags", [self.tag, "retained:rollback"]),
            ("RepoTags", ["unexpected:tag"]),
        ):
            with self.subTest(key=key, value=value):
                info = deepcopy(self.image)
                info[key] = value
                with self.assertRaises(RuntimeError):
                    cleanup.validate_candidate(self.prefix, self.tag, info, set())

    def test_arbitrary_candidate_is_rejected(self):
        with self.assertRaises(RuntimeError):
            cleanup.validate_candidate("not-approved", self.tag, self.image, set())

    def test_no_approval_stops_before_any_remote_command(self):
        with patch.object(cleanup, "inspect_runtime") as inspect:
            with self.assertRaises(RuntimeError):
                cleanup.main("not-approved")
            inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
