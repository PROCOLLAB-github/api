"""Inspect the existing production containers using read-only database queries."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

REPO = Path("/home/app/procollab-backend")
EXPECTED_DATABASE_NAME_B64 = globals().get("EXPECTED_DATABASE_NAME_B64", "")
EXPECTED_DATABASE_ENDPOINT_B64 = globals().get("EXPECTED_DATABASE_ENDPOINT_B64", "")
PROBE = r"""
import base64, json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'procollab.settings')
import django
django.setup()
from django.conf import settings
from django.db import connection, transaction
import redis
result = {
    'django': django.get_version(),
    'nextgen_surface_configured': hasattr(settings, 'NEXTGEN_SURFACE_ENABLED'),
    'nextgen_surface_enabled': getattr(settings, 'NEXTGEN_SURFACE_ENABLED', None),
}
stage = 'database_connection'
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout = '10s'")
        cursor.execute("SET LOCAL lock_timeout = '3s'")
        cursor.execute(
            "SELECT current_database(), current_setting('server_version_num')::int, "
            "pg_database_size(current_database())"
        )
        name, version, size = cursor.fetchone()
        matches_config = name == settings.DATABASES['default']['NAME']
        expected = base64.b64decode(EXPECTED_DATABASE_NAME_B64).decode()
        matches_expected = bool(expected) and name == expected
        endpoint = json.loads(base64.b64decode(EXPECTED_DATABASE_ENDPOINT_B64))
        runtime = settings.DATABASES['default']
        endpoint_matches = (
            str(runtime.get('HOST', '')).lower() == str(endpoint.get('HOST', '')).lower()
            and str(runtime.get('PORT') or '5432') == str(endpoint.get('PORT') or '5432')
            and name == endpoint.get('NAME')
        )
        looks_nonproduction = any(marker in name.lower() for marker in ('dev', 'test', '_ci'))
        result.update(database_matches_runtime=matches_config,
                      database_matches_github=matches_expected and endpoint_matches,
                      nonproduction_name_marker=looks_nonproduction)
        if not matches_config or not matches_expected or not endpoint_matches:
            raise RuntimeError('Unexpected production database')
        result.update(postgresql_version_num=version, database_bytes=size, supports_django_52=version >= 140000)
        stage = 'migration_metadata'
        cursor.execute('SELECT app,name FROM django_migrations ORDER BY app,name')
        result['applied_migrations'] = cursor.fetchall()
        cursor.execute("SELECT has_schema_privilege(current_user,'public','CREATE')")
        result['migration_role_can_create_in_public'] = cursor.fetchone()[0]
        cursor.execute(
            "SELECT count(*),bool_and(pg_has_role(current_user,relowner,'USAGE')) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='r'"
        )
        result['table_count'], result['migration_role_owns_existing_tables'] = cursor.fetchone()
stage = 'redis_ping'
client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=5, socket_timeout=5)
try:
    result['redis_ping_ok'] = bool(client.ping())
finally:
    client.close()
print(json.dumps(result))
"""


def probe_source():
    source = "EXPECTED_DATABASE_NAME_B64 = " + repr(EXPECTED_DATABASE_NAME_B64) + "\n"
    source += (
        "EXPECTED_DATABASE_ENDPOINT_B64 = "
        + repr(EXPECTED_DATABASE_ENDPOINT_B64)
        + "\n"
    )
    source += 'stage="django_setup"\ntry:\n' + textwrap.indent(PROBE, "    ")
    source += """
except Exception as error:
    import json
    safe = globals().get('result', {})
    safe.update(probe_error_type=type(error).__name__, probe_error_stage=stage)
    print(json.dumps(safe))
"""
    return source.encode()


def read(args, *, source=None):
    result = subprocess.run(
        args, input=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90
    )
    if result.returncode:
        raise RuntimeError("Read-only production command failed: " + "-".join(args[:2]))
    return result.stdout.decode().strip()


def repository_read(*arguments):
    # A root SSH login must read an app-owned repository as app, not run its hooks as root.
    owner = REPO.stat().st_uid
    command = ["git", "-C", str(REPO)]
    if os.geteuid() == 0 and owner != 0:
        from pwd import getpwuid

        command = ["sudo", "-n", "-u", getpwuid(owner).pw_name] + command
    return read(command + list(arguments))


def storage_summary(image_id):
    mounts = []
    for row in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = row.split(" - ", 1)
        parts = left.split()
        source = right.split()[1]
        location = parts[4].replace("\\040", " ")
        if location != "/" and not source.startswith("/dev/"):
            continue
        if location.startswith("/var/lib/docker/") or not Path(location).is_dir():
            continue
        usage = shutil.disk_usage(location)
        mounts.append(
            {"path": location, "total_bytes": usage.total, "free_bytes": usage.free}
        )
    image_bytes = json.loads(
        read(["docker", "image", "inspect", "--format", "{{json .Size}}", image_id])
    )
    docker = read(["docker", "system", "df", "--format", "{{json .}}"])
    images = read(["docker", "system", "df", "--verbose"])
    return {
        "mounts": mounts,
        "running_image_bytes": image_bytes,
        "docker_usage": [json.loads(line) for line in docker.splitlines()],
        "image_disk_usage": images.split("Containers space usage:", 1)[0].strip(),
    }


def inspect_runtime():
    if not REPO.is_dir() or REPO.resolve() != REPO:
        raise RuntimeError("Unexpected repository location")
    compose = [
        "docker",
        "compose",
        "-f",
        str(REPO / "docker-compose.prod-ci.yml"),
        "-p",
        "prod",
    ]
    # IMAGE_TAG is required by Compose interpolation even for a read-only ps command.
    os.environ.setdefault("IMAGE_TAG", "preflight-unused")
    containers = {}
    mounts = {}
    for service in ("web", "celerys"):
        container = read(compose + ["ps", "-q", service])
        if not container or "\n" in container:
            raise RuntimeError("Expected exactly one production service container")
        info = json.loads(
            read(["docker", "inspect", "--format", "{{json .}}", container])
        )
        labels = info["Config"].get("Labels", {})
        if (
            labels.get("com.docker.compose.project") != "prod"
            or not info["State"]["Running"]
        ):
            raise RuntimeError("Unexpected production container")
        files = labels.get("com.docker.compose.project.config_files", "").split(",")
        if str(REPO / "docker-compose.prod-ci.yml") not in files:
            raise RuntimeError("Production compose path does not match")
        containers[service] = (container, info["Image"], info["Config"]["Image"])
        mounts[service] = [
            {
                "type": mount["Type"],
                "destination": mount["Destination"],
                "writable": mount["RW"],
            }
            for mount in info.get("Mounts", [])
        ]
    if containers["web"][1] != containers["celerys"][1]:
        raise RuntimeError("Production web and worker images differ")
    result = json.loads(
        read(
            [
                "docker",
                "exec",
                "-i",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                containers["web"][0],
                "python",
                "-",
            ],
            source=probe_source(),
        )
    )
    if result.get("probe_error_type"):
        sys.stdout.write("PROD_PROBE_DIAGNOSTIC=" + json.dumps(result) + "\n")
        sys.stdout.flush()
        raise RuntimeError("Production probe stopped at " + result["probe_error_stage"])
    result.update(
        source_sha=repository_read("rev-parse", "HEAD"),
        tracked_tree_clean=not bool(
            repository_read("status", "--porcelain", "--untracked-files=no")
        ),
        tracked_changed_paths=repository_read(
            "diff", "HEAD", "--name-only"
        ).splitlines(),
        web_worker_same_image=True,
        image=containers["web"][2],
        image_id=containers["web"][1],
        disk_free_bytes=shutil.disk_usage(REPO).free,
        service_mounts=mounts,
    )
    result["storage"] = storage_summary(containers["web"][1])
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    result["memory_available_kib"] = int(memory["MemAvailable"].split()[0])
    result["native_postgres_clients"] = {}
    for client in ("pg_dump", "pg_restore"):
        executable = shutil.which(client)
        result["native_postgres_clients"][client] = (
            read([executable, "--version"]) if executable else None
        )
    return result, containers


def main():
    result, _containers = inspect_runtime()
    sys.stdout.write("PROD_READONLY_PREFLIGHT=" + json.dumps(result) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stdout.write(
            "PROD_READONLY_PREFLIGHT_FAILED=" + type(error).__name__ + "\n"
        )
        raise SystemExit(1)
