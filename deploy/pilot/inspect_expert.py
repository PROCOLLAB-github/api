"""Прочитать версии и настройки действующего пилота, не меняя файлы и БД."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

BUNDLE_HASHES = {
    "management_base.json": "b73b82034a421224d78409f062a0653df5891af0d0cf28c2575910e6281d497d",
    "overall_base.json": "6ce9e753371c8cd5432d67592e71bcc637bdb54149de56eb61b1915b238ae833",
    "hosted.py": "865ab0d364436901b562d5c30f5522d7b6228f5ca7a933a63511fe30d7441a52",
    "runtime_import.py": "35bdeda83a3eb55d81f30f0555257fe6c7a6de104322d7504dcfbac51aff4fd3",
    "upgrade_frontend.py": "25300e5b2f305b3dfdec98458a445add7c060182ed5517d3820c4368b7eefbd3",
    "upgrade_invites.py": "8a650e75e9228cf0f7547693ce3a78657c300080361723e6d62ff4e17058bbf2",
    "upgrade_overall.py": "8da6e6cecaf1f91c1f32190508d68017bce8c7dac4f7c43d752a238173ff9202",
    "upgrade_management.py": "b3e8f96cd4e1bbaf2e69d416ed60aa28affd3c8f3764d6ee43abe0b3d70d5d51",
}
FEATURE_FILES = (
    "partner_programs/organizer_signals.py",
    "project_rates/program_experts.py",
    "project_rates/project_scoring.py",
)


def check_bundle(bundle):
    if bundle.resolve() != bundle or bundle.is_symlink():
        raise ValueError("Нужен обычный каталог исходного проверенного пакета.")
    for name, expected in BUNDLE_HASHES.items():
        path = bundle / name
        if (
            not path.is_file()
            or path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Изменен исходный пакет: " + name)


def inspect(bundle):
    check_bundle(bundle)
    sys.path.insert(0, str(bundle))
    import upgrade_management as previous

    hosted = previous.hosted
    hosted.scope()
    record = previous.load_record()
    web = hosted.candidate()
    hosted.require(
        record["phase"] == "active" and web and web["State"]["Running"],
        "Нужен действующий пилот после обновления управления.",
    )
    expected = {
        **previous.overall.BASE["runtime_hashes"],
        **previous.overall.BASE["target_hashes"],
        **previous.BASE["target_hashes"],
    }
    for name in FEATURE_FILES:
        expected.setdefault(name, None)
    script = (
        "import hashlib,json,sys;from pathlib import Path;root=Path('/procollab');"
        "names=json.load(sys.stdin);print(json.dumps({n:hashlib.sha256((root/n).read_bytes())"
        ".hexdigest() if (root/n).is_file() and not (root/n).is_symlink() else None for n in names}))"
    )
    result = hosted.docker(
        "exec",
        "-i",
        web["Id"],
        "python",
        "-B",
        "-c",
        script,
        input=json.dumps(sorted(expected)),
        capture_output=True,
        text=True,
        timeout=45,
    )
    hosted.require(result.returncode == 0, "Не прочитаны исходники API пилота.")
    actual = json.loads(result.stdout)
    changed = {
        name: actual.get(name)
        for name in sorted(expected)
        if actual.get(name) != expected[name]
    }
    frontend_changed = []
    for name, digest in previous.BASE["target_frontend_files"].items():
        path = previous.auth.frontend_path(name)
        if not path.is_file() or path.is_symlink() or hosted.digest(path) != digest:
            frontend_changed.append(name)
    probe = r"""
import json
import django
django.setup()
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
assert connection.settings_dict['NAME'] == 'procollab_white_label_pilot_v2'
assert connection.settings_dict['USER'] == 'procollab_pilot_v2'
keys = [
    'WHITE_LABEL_ENABLED', 'WHITE_LABEL_PROGRAM_ID', 'WHITE_LABEL_BRAND_NAME',
    'WHITE_LABEL_FRONTEND_URL', 'WHITE_LABEL_LOGO_URL',
    'WHITE_LABEL_ORGANIZERS_ARE_EXPERTS', 'PROGRAM_SOLUTIONS_ENABLED',
    'ROOT_URLCONF', 'FORCE_SCRIPT_NAME', 'EMAIL_BACKEND',
]
executor = MigrationExecutor(connection)
leaves = executor.loader.graph.leaf_nodes()
print(json.dumps({
    'settings': {key: getattr(settings, key, None) for key in keys},
    'database': connection.settings_dict['NAME'],
    'migration_leaves': sorted(leaves),
    'unapplied_migrations': [list(node) for node, backwards in executor.migration_plan(leaves)],
    'partner_programs_applied': sorted(
        name for app, name in executor.loader.applied_migrations if app == 'partner_programs'
    ),
}))
"""
    result = hosted.docker(
        "exec",
        web["Id"],
        "python",
        "-B",
        "-c",
        probe,
        capture_output=True,
        text=True,
        timeout=45,
    )
    hosted.require(result.returncode == 0, "Не прочитаны настройки и миграции пилота.")
    database = json.loads(result.stdout.splitlines()[-1])
    state = hosted.state_read()
    labels = web["Config"].get("Labels") or {}
    return {
        "changes_applied": False,
        "pilot": {
            "recorded_backend_revision": record["release"],
            "recorded_frontend_revision": record["frontend_revision"],
            "container_backend_revision": labels.get(previous.files.REVISION_LABEL),
            "web_matches_record": previous.overall.container_identity(web)
            == record["new_web"],
            "state_matches_record": state == record["new_state"],
            "api_files_checked": len(expected),
            "api_matches_recorded_release": not changed,
            "changed_api_files": changed,
            "frontend_matches_recorded_release": not frontend_changed,
            "changed_frontend_files": frontend_changed,
            "routes_match_record": hosted.digest(hosted.ROUTES) == record["routes_after"],
            "maps_match_state": hosted.digest(hosted.MAPS) == state["new_maps_sha256"],
        },
        **database,
        "dev_http": hosted.dev_health(),
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
