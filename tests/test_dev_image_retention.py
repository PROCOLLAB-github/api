import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts import dev_image_retention as service


class DevImageRetentionTests(unittest.TestCase):
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)

    def image(self, number, age):
        return {
            "id": f"sha256:{number:064x}",
            "tags": [f"procollab-dev-api:{number:040x}"],
            "created": (self.now - timedelta(days=age)).isoformat(),
        }

    def test_plan_keeps_all_container_images_newest_three_and_unknown_images(self):
        rows = [self.image(number, number) for number in range(1, 7)]
        foreign = self.image(7, 9)
        foreign["tags"] = ["other-project:old"]
        mixed = self.image(8, 9)
        mixed["tags"].append("api-web:latest")
        dangling = self.image(9, 9)
        dangling["tags"] = []
        unreachable = self.image(10, 9)
        images = {
            row["id"]: row for row in rows + [foreign, mixed, dangling, unreachable]
        }
        containers = [
            {"id": "stopped-container", "image": rows[4]["id"], "state": "exited"}
        ]
        plan = service.plan(
            images,
            containers,
            ["volume"],
            self.now,
            lambda sha: sha != f"{10:040x}",
        )
        self.assertEqual(
            {row["id"] for row in plan["candidates"]}, {rows[3]["id"], rows[5]["id"]}
        )
        self.assertEqual(plan["protected_count"], 8)
        # Time alone does not change the inventory digest while candidates stay identical.
        self.assertEqual(
            plan["sha256"],
            service.plan(
                images,
                containers,
                ["volume"],
                self.now + timedelta(minutes=1),
                lambda sha: sha != f"{10:040x}",
            )["sha256"],
        )

    def test_young_images_are_not_removed_even_when_more_than_three_exist(self):
        images = {
            row["id"]: row
            for row in [self.image(number, 0.1 * number) for number in range(1, 7)]
        }
        self.assertEqual(
            service.plan(images, [], [], self.now, lambda sha: True)["candidates"], []
        )

    def test_nanosecond_docker_timestamp_is_supported(self):
        self.assertEqual(
            service.created_at({"created": "2026-10-25T00:00:00.123456789Z"}).microsecond,
            123456,
        )

    @patch.object(service.subprocess, "run")
    def test_wrong_review_digest_never_mutates_docker(self, run):
        with self.assertRaises(RuntimeError):
            service.apply({"sha256": "reviewed", "candidates": []}, "changed", {}, [], [])
        run.assert_not_called()

    @patch.object(service.subprocess, "run")
    @patch.object(service, "containers", return_value=[{"image": "new-container"}])
    def test_new_container_aborts_before_removing_any_tag(self, containers, run):
        image = self.image(1, 9)
        with self.assertRaises(RuntimeError):
            service.apply(
                {"sha256": "same", "candidates": [image]},
                "same",
                {image["id"]: image},
                [],
                [],
            )
        run.assert_not_called()

    @patch.object(service, "containers", return_value=[])
    @patch.object(service, "volumes", return_value=["volume"])
    @patch.object(service, "inventory")
    @patch.object(service.subprocess, "run")
    def test_removes_only_reviewed_tags_without_force_or_parent_pruning(
        self, run, inventory, volumes, containers
    ):
        image, protected = self.image(1, 9), self.image(2, 1)
        image["tags"].append(image["tags"][0] + "-0123456789ab")
        before = {row["id"]: row for row in (image, protected)}
        inventory.side_effect = [before, {protected["id"]: protected}]
        service.apply(
            {"sha256": "same", "candidates": [image]}, "same", before, [], ["volume"]
        )
        self.assertEqual(run.call_count, 2)
        for call, tag in zip(run.call_args_list, image["tags"]):
            self.assertEqual(call.args, (["docker", "image", "rm", "--no-prune", tag],))
            self.assertEqual(call.kwargs, {"check": True})


if __name__ == "__main__":
    unittest.main()
