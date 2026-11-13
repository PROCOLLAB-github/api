"""Read-only обследование существующего пилота. Секреты и исходники не выводятся."""

import ast
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
from urllib.request import urlopen

BASE_REVISION = "b4575a0770c0515a8099cd3920416a7cbcf953bf"
ROOT = Path("/opt/procollab-white-label-pilot")
WEB = "procollab-white-label-pilot-web-1"


def docker(*args):
    return subprocess.check_output(
        ["docker", "--host=unix:///var/run/docker.sock", *args], text=True, timeout=30
    )


def safe_routes(path):
    result = []
    for line in path.read_text().splitlines():
        if re.match(
            r"\s*(location|root|alias|proxy_pass|auth_basic|auth_basic_user_file|try_files|rewrite)\b",
            line,
        ):
            value = line.split("{", 1)[0].split(";", 1)[0].strip()
            result.append(re.sub(r"(://)[^/\s]*@", r"\1<скрыто>@", value))
    return result


def main():
    backend = ROOT / "backend"
    if not (backend / "pilot_hosted_settings.py").is_file():
        raise SystemExit("Ожидался существующий pilot_hosted_settings.py. Изменений нет.")
    profile = ast.parse((backend / "pilot_hosted_settings.py").read_text())
    report = {
        "backend": str(backend),
        "reference_api": BASE_REVISION,
        "profile_imports": [],
        "profile_definitions": [],
        "profile_assignments": [],
        "root_entries": sorted(p.name for p in ROOT.iterdir()),
    }
    for node in profile.body:
        if isinstance(node, ast.ImportFrom):
            report["profile_imports"].append(node.module)
        elif isinstance(node, ast.Import):
            report["profile_imports"].extend(alias.name for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            report["profile_definitions"].append(node.name)
        elif isinstance(node, ast.Assign):
            report["profile_assignments"].extend(ast.unparse(t) for t in node.targets)

    # Читаем неизменяемую публичную reference revision в памяти, не распаковываем.
    url = f"https://codeload.github.com/PROCOLLAB-github/api/tar.gz/{BASE_REVISION}"
    with urlopen(url, timeout=30) as response:
        source = response.read(64 * 1024 * 1024 + 1)
    if len(source) > 64 * 1024 * 1024:
        raise SystemExit("Reference archive слишком велик. Изменений нет.")
    changed, missing, migrations = [], [], []
    with tarfile.open(fileobj=io.BytesIO(source), mode="r:gz") as archive:
        for member in archive:
            relative = member.name.partition("/")[2]
            if not member.isfile() or not relative:
                continue
            parts = Path(relative).parts
            if (
                len(parts) == 3
                and parts[1] == "migrations"
                and parts[2].endswith(".py")
                and parts[2] != "__init__.py"
            ):
                migrations.append((parts[0], parts[2][:-3]))
            if not (
                relative.endswith(".py") or relative in ("pyproject.toml", "poetry.lock")
            ):
                continue
            if (
                "/tests/" in relative
                or relative.startswith(("scripts/", "deploy/"))
                or "/migrations/" in relative
            ):
                continue
            current = backend / relative
            if not current.is_file():
                missing.append(relative)
            elif (
                hashlib.sha256(current.read_bytes()).digest()
                != hashlib.sha256(archive.extractfile(member).read()).digest()
            ):
                changed.append(relative)
    report["reference_missing_count"] = len(missing)
    report["reference_changed_count"] = len(changed)
    report["reference_missing"] = missing[:40]
    report["reference_changed"] = changed[:40]
    report["routes"] = safe_routes(ROOT / "nginx/routes.inc")

    probe = """
import json
import django
django.setup()
from django.apps import apps
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.contrib.auth import get_user_model
result = {"applied": list(MigrationRecorder.Migration.objects.values_list("app", "name"))}
users = get_user_model().objects
result["user_count"] = users.count()
result["non_synthetic_user_count"] = users.exclude(email__iendswith="@example.test").count()
try:
    model = apps.get_model("partner_programs", "ProgramRegistration")
    result["registration_versions"] = list(model.objects.values("program_id", "published_version"))
except Exception:
    result["registration_versions"] = "not_available"
with connection.cursor() as cursor:
    cursor.execute("SELECT pg_database_size(current_database())")
    result["database_size_bytes"] = cursor.fetchone()[0]
print(json.dumps(result))
"""
    database = json.loads(docker("exec", WEB, "python", "-c", probe))
    applied = {tuple(pair) for pair in database.pop("applied")}
    outstanding = sorted(set(migrations) - applied)
    database["reference_unapplied_count"] = len(outstanding)
    database["reference_unapplied_migrations"] = outstanding[:30]
    report["database"] = database
    info = json.loads(docker("info", "--format", "{{json .}}"))
    report["docker_storage_driver"] = info["Driver"]
    report["image_size_bytes"] = int(
        docker(
            "image",
            "inspect",
            "--format",
            "{{.Size}}",
            "procollab-white-label-pilot-base:20261109",
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
