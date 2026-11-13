"""Показать различия с историческим снимком пилота без изменения стенда."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

# Проверенный пакет 47175a2. Не импортируем чужие или измененные root-скрипты.
BUNDLE_HASHES = {
    "management_base.json": "0f6f2ae5cc1582152fc6ea3f61c48efea15d940a17c7a89e86e41259739e50d0",
    "overall_base.json": "6ce9e753371c8cd5432d67592e71bcc637bdb54149de56eb61b1915b238ae833",
    "hosted.py": "865ab0d364436901b562d5c30f5522d7b6228f5ca7a933a63511fe30d7441a52",
    "runtime_import.py": "35bdeda83a3eb55d81f30f0555257fe6c7a6de104322d7504dcfbac51aff4fd3",
    "upgrade_frontend.py": "25300e5b2f305b3dfdec98458a445add7c060182ed5517d3820c4368b7eefbd3",
    "upgrade_invites.py": "8a650e75e9228cf0f7547693ce3a78657c300080361723e6d62ff4e17058bbf2",
    "upgrade_overall.py": "8da6e6cecaf1f91c1f32190508d68017bce8c7dac4f7c43d752a238173ff9202",
    "upgrade_management.py": "b3e8f96cd4e1bbaf2e69d416ed60aa28affd3c8f3764d6ee43abe0b3d70d5d51",
}

CONTAINER_FIELDS = ("container_id", "image_id", "started_at", "configuration_hash")


def snapshot_changes(before, after):
    containers = []
    previous = before.get("containers", {})
    current = after.get("containers", {})
    for name in sorted(set(previous) | set(current)):
        old, new = previous.get(name), current.get(name)
        if old == new:
            continue
        fields = (
            list(CONTAINER_FIELDS)
            if old is None or new is None
            else [field for i, field in enumerate(CONTAINER_FIELDS) if old[i] != new[i]]
        )
        containers.append({"name": name, "changed": fields})
    old_files, new_files = before.get("files", {}), after.get("files", {})
    files = [
        name
        for name in sorted(set(old_files) | set(new_files))
        if old_files.get(name) != new_files.get(name)
    ]
    return {
        "containers": containers,
        "files": files,
        "nginx_changed": before.get("nginx") != after.get("nginx"),
    }


def check_bundle(bundle):
    if bundle.resolve() != bundle or bundle.is_symlink():
        raise ValueError("Нужен обычный каталог проверенного пакета.")
    for name, expected in BUNDLE_HASHES.items():
        path = bundle / name
        if (
            not path.is_file()
            or path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Изменен файл пакета: " + name)


def inspect(bundle):
    check_bundle(bundle)
    sys.path.insert(0, str(bundle))
    import upgrade_management as upgrade

    upgrade.verify_bundle(bundle)
    upgrade.hosted.scope()
    previous = upgrade.overall.load_record()
    old_web = upgrade.hosted.inspect(previous["old_container_id"])
    current = upgrade.overall.outside_snapshot(old_web)
    changes = snapshot_changes(previous["outside"], current)
    web = upgrade.hosted.candidate()
    runtime_matches = False
    if web:
        try:
            upgrade.verify_runtime(web, updated=False)
            runtime_matches = True
        except upgrade.hosted.Refused:
            pass
    frontend_changed = []
    for name, expected in upgrade.BASE["frontend_files"].items():
        path = upgrade.auth.frontend_path(name)
        if (
            not path.is_file()
            or path.is_symlink()
            or upgrade.hosted.digest(path) != expected
        ):
            frontend_changed.append(name)
    return {
        "changes_applied": False,
        "historical_snapshot_changes": changes,
        "pilot": {
            "management_record_exists": upgrade.RECORD.exists(),
            "web_matches_overall_record": bool(
                web and upgrade.overall.container_identity(web) == previous["new_web"]
            ),
            "state_matches_overall_record": upgrade.hosted.state_read()
            == previous["new_state"],
            "backend_matches_expected": runtime_matches,
            "frontend_changed": frontend_changed,
            "routes_match_state": upgrade.hosted.digest(upgrade.hosted.ROUTES)
            == previous["new_state"]["new_routes_sha256"],
            "maps_match_state": upgrade.hosted.digest(upgrade.hosted.MAPS)
            == previous["new_state"]["new_maps_sha256"],
        },
        "dev_http": upgrade.hosted.dev_health(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = inspect(args.bundle.absolute())
    except Exception as error:
        sys.exit("Диагностика остановлена: " + str(error))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
