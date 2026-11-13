"""Проверки границ pilot nginx и защиты обновления без доступа к серверу."""

from copy import deepcopy
from pathlib import Path
import json
import unittest
from unittest.mock import patch

import upgrade_management as upgrade


class ManagementSnapshotGuardTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            "containers": {
                name: [name + "-old-id", "image-id", "started-before", "config-hash"]
                for name in upgrade.overall.OUTSIDE
            },
            "files": {
                str(upgrade.ROOT / ".env"): "environment-hash",
                str(upgrade.hosted.ROUTES): "routes-hash",
                str(upgrade.hosted.MAPS): "maps-hash",
            },
            "nginx": "nginx-hash",
        }
        self.current = deepcopy(self.previous)
        for name in ("api-web-1", "api-redis-1", "api_celery"):
            self.current["containers"][name] = [
                name + "-new-id",
                "new-image-id",
                "started-now",
                "new-config-hash",
            ]
        self.record = {"outside": self.previous, "old_container_id": "old-pilot-web"}

    def verify_predecessor(self, current):
        with patch.object(upgrade.hosted, "inspect"), patch.object(
            upgrade.overall, "outside_snapshot", return_value=current
        ), patch.object(upgrade.hosted, "dev_health", return_value=200) as health:
            changed = upgrade.verify_predecessor(self.record)
            health.assert_called_once_with()
            return changed

    def test_historical_dev_redeployment_accepts_current_health_without_rewriting_history(
        self,
    ):
        before = deepcopy(self.record)
        self.assertEqual(
            self.verify_predecessor(self.current),
            ["api-redis-1", "api-web-1", "api_celery"],
        )
        self.assertEqual(self.record, before)
        self.assertEqual(self.verify_predecessor(deepcopy(self.previous)), [])

    def test_historical_pilot_database_files_and_nginx_remain_strict(self):
        for name in upgrade.overall.OUTSIDE:
            if name in ("api-web-1", "api-redis-1", "api_celery"):
                continue
            for index in range(4):
                current = deepcopy(self.current)
                current["containers"][name][index] = "unexpected-change"
                with self.subTest(container=name, identity_field=index):
                    with self.assertRaises(upgrade.hosted.Refused):
                        self.verify_predecessor(current)
        for name in self.previous["files"]:
            current = deepcopy(self.current)
            current["files"][name] = "unexpected-change"
            with self.subTest(file=name), self.assertRaises(upgrade.hosted.Refused):
                self.verify_predecessor(current)
        current = deepcopy(self.current)
        current["nginx"] = "unexpected-change"
        with self.assertRaises(upgrade.hosted.Refused):
            self.verify_predecessor(current)

    def test_container_set_changes_are_rejected(self):
        for operation in ("missing-dev", "missing-database", "extra"):
            current = deepcopy(self.current)
            if operation == "missing-dev":
                del current["containers"]["api-web-1"]
            elif operation == "missing-database":
                del current["containers"][upgrade.hosted.PG]
            else:
                current["containers"]["unexpected"] = ["id"] * 4
            with self.subTest(operation=operation):
                with self.assertRaises(upgrade.hosted.Refused):
                    self.verify_predecessor(current)

    def test_unhealthy_current_dev_stops_before_installation(self):
        with patch.object(upgrade.hosted, "inspect"), patch.object(
            upgrade.overall, "outside_snapshot", return_value=self.current
        ), patch.object(
            upgrade.hosted,
            "dev_health",
            side_effect=upgrade.hosted.Refused("DEV unhealthy"),
        ):
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.verify_predecessor(self.record)

    def test_current_guard_rejects_every_dev_identity_change_during_installation(self):
        # Историческое обновление DEV допустимо; новое изменение после фиксации — нет.
        record = {"outside": self.current, "old_container_id": "old-pilot-web"}
        before = deepcopy(record)
        for name in ("api-web-1", "api-redis-1", "api_celery"):
            for index in range(4):
                changed = deepcopy(self.current)
                changed["containers"][name][index] = "changed-during-installation"
                with self.subTest(container=name, identity_field=index):
                    with patch.object(upgrade.hosted, "inspect"), patch.object(
                        upgrade, "outside_snapshot", return_value=changed
                    ), patch.object(upgrade.hosted, "dev_health") as health:
                        with self.assertRaises(upgrade.hosted.Refused):
                            upgrade.verify_outside(record)
                        health.assert_not_called()
        with patch.object(upgrade.hosted, "inspect"), patch.object(
            upgrade, "outside_snapshot", return_value=deepcopy(self.current)
        ), patch.object(upgrade.hosted, "dev_health", return_value=200) as health:
            self.assertEqual(upgrade.verify_outside(record), 200)
            health.assert_called_once_with()
        self.assertEqual(record, before)


class ManagementUpgradeTests(unittest.TestCase):
    def test_search_smoke_closes_its_session_even_when_the_search_fails(self):
        for fail_search in (False, True):
            calls = []

            def health(url, *, headers=None, body=None):
                calls.append((url, dict(headers or {}), body))
                if url.endswith("/api/token/"):
                    return 200, {}, b'{"access":"test-access","refresh":"test-refresh"}'
                if url.endswith("/auth/logout/"):
                    return 205, {}, b""
                if headers.get("Authorization"):
                    return (
                        (500, {}, b"{}")
                        if fail_search
                        else (200, {}, b'{"results":[{"email":"member@example.test"}]}')
                    )
                return 200, {}, b'{"count":0}'

            with self.subTest(fail_search=fail_search), patch.object(
                upgrade.hosted, "health", side_effect=health
            ), patch.object(
                upgrade.hosted,
                "environment",
                return_value={"PILOT_ACCOUNT_PASSWORD": "test-only"},
            ):
                if fail_search:
                    with self.assertRaises(upgrade.hosted.Refused):
                        upgrade.candidate_search_smoke()
                else:
                    upgrade.candidate_search_smoke()
            logout = [call for call in calls if call[0].endswith("/auth/logout/")]
            self.assertEqual(len(logout), 1)
            self.assertEqual(json.loads(logout[0][2]), {"refresh_token": "test-refresh"})

    def test_gate_removal_preserves_backend_bearer_and_all_other_routes(self):
        before = (
            (Path(__file__).parent / "hosted-routes.inc.template")
            .read_text()
            .replace("@@ROOT@@", str(upgrade.ROOT))
        )
        after = upgrade.public_routes(before)
        self.assertIn("auth_basic off;", after)
        self.assertNotIn("auth_basic_user_file", after)
        self.assertIn("Max-Age=0", after)
        self.assertEqual(
            before.split("location = /admin", 1)[1],
            after.split("location = /admin", 1)[1],
        )
        self.assertEqual(
            after.count("proxy_set_header Authorization $ppv2_authorization;"), 2
        )

    def test_unknown_or_already_public_gate_is_refused(self):
        for before in (
            "auth_basic off;",
            "auth_basic $different;",
            "",
            "auth_basic $ppv2_realm;" * 2,
        ):
            with self.subTest(before=before), self.assertRaises(upgrade.hosted.Refused):
                upgrade.public_routes(before)

    def test_nginx_comparison_excludes_only_the_owned_include(self):
        prefix = "# configuration file /etc/nginx/nginx.conf:\nhttp { include sites-enabled/*; }\n"
        owned = f"# configuration file {upgrade.hosted.ROUTES}:\nauth_basic off;\n"
        dev = "# configuration file /etc/nginx/sites-enabled/dev.procollab.ru:\nserver_name dev.procollab.ru;\n"
        self.assertEqual(upgrade.nginx_outside(prefix + owned + dev), prefix + dev)
        self.assertNotEqual(
            upgrade.nginx_outside(prefix + owned + dev),
            upgrade.nginx_outside(
                prefix + owned + dev.replace("dev.procollab.ru", "other.example.test")
            ),
        )
        for config in (prefix + dev, prefix + owned + owned + dev):
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.nginx_outside(config)

    def test_runtime_rejects_modified_unchanged_source_and_missing_new_file(self):
        expected = {
            **upgrade.overall.BASE["runtime_hashes"],
            **upgrade.overall.BASE["target_hashes"],
        }
        for name in upgrade.PATCH_FILES:
            expected.setdefault(name, None)
        with patch.object(upgrade, "runtime_fingerprint", return_value=expected):
            upgrade.verify_runtime({}, updated=False)
        updated = {**expected, **upgrade.BASE["target_hashes"]}
        with patch.object(upgrade, "runtime_fingerprint", return_value=updated):
            upgrade.verify_runtime({}, updated=True)
        changed = deepcopy(updated)
        changed["users/serializers.py"] = "0" * 64
        with patch.object(upgrade, "runtime_fingerprint", return_value=changed):
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.verify_runtime({}, updated=True)
        changed = deepcopy(updated)
        changed["partner_programs/services/white_label_experts.py"] = None
        with patch.object(upgrade, "runtime_fingerprint", return_value=changed):
            with self.assertRaises(upgrade.hosted.Refused):
                upgrade.verify_runtime({}, updated=True)


if __name__ == "__main__":
    unittest.main()
