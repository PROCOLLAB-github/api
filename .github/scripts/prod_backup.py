"""Create a protected production DB/image backup; never migrate or restart services."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from uuid import uuid4

from prod_preflight import REPO, inspect_runtime, read

BACKUPS = Path("/home/app/procollab-dependency-backups")
RESERVE = 1024**3


def emit(value):
    sys.stdout.write(value + "\n")
    sys.stdout.flush()


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_failure(stderr):
    lowered = stderr.lower()
    for marker, category in (
        (b"permission denied", "permission_denied"),
        (b"authentication failed", "authentication_failed"),
        (b"connection refused", "connection_refused"),
        (b"server version", "client_server_version"),
        (b"lock timeout", "lock_timeout"),
        (b"timeout", "timeout"),
    ):
        if marker in lowered:
            return category
    return "command_failed"


def guarded_archive(args, destination, *, stage, environment=None, timeout=900):
    """Abort our writer before it can exhaust the filesystem used by production."""
    with destination.open("xb") as archive, tempfile.TemporaryFile(
        dir=destination.parent
    ) as errors:
        os.chmod(destination, 0o600)
        process = subprocess.Popen(args, stdout=archive, stderr=errors, env=environment)
        start = time.monotonic()
        try:
            while process.poll() is None:
                if shutil.disk_usage(destination.parent).free < RESERVE:
                    raise RuntimeError("Production backup stopped: disk reserve reached")
                if time.monotonic() - start > timeout:
                    raise RuntimeError("Production backup stopped: writer timeout")
                time.sleep(1)
            if process.returncode:
                errors.seek(0)
                category = safe_failure(errors.read(65536))
                raise RuntimeError("Production backup failed: " + stage + ":" + category)
            archive.flush()
            os.fsync(archive.fileno())
            os.chmod(destination, 0o600)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def native_clients(major):
    pairs = [
        (
            Path(f"/usr/lib/postgresql/{major}/bin/pg_dump"),
            Path(f"/usr/lib/postgresql/{major}/bin/pg_restore"),
        )
    ]
    if shutil.which("pg_dump") and shutil.which("pg_restore"):
        pairs.append((Path(shutil.which("pg_dump")), Path(shutil.which("pg_restore"))))
    for dump, restore in pairs:
        versions = []
        for executable in (dump, restore):
            if not executable.is_file():
                break
            result = subprocess.run(
                [str(executable), "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )
            match = re.search(rb"PostgreSQL\) (\d+)", result.stdout)
            versions.append(
                int(match.group(1)) if result.returncode == 0 and match else 0
            )
        if versions == [major, major]:
            return [str(dump)], [str(restore), "--file=/dev/null"]
    return None


def validate_database_archive(path, restore_command):
    # Unbuffered: inherited stdin must start at the real OS file offset zero.
    with path.open("rb", buffering=0) as archive, tempfile.TemporaryFile(
        dir=path.parent
    ) as errors:
        if archive.read(5) != b"PGDMP":
            raise RuntimeError("Invalid production database archive")
        archive.seek(0)
        result = subprocess.run(
            restore_command,
            stdin=archive,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            timeout=900,
        )
        if result.returncode:
            raise RuntimeError("Production archive full-read validation failed")


def validate_image_archive(path, expected_id):
    with tarfile.open(path, "r:") as archive:
        member = archive.getmember("manifest.json")
        if member.size > 1024 * 1024 or not member.isfile():
            raise RuntimeError("Unexpected image manifest")
        manifest = json.load(archive.extractfile(member))
        if len(manifest) != 1:
            raise RuntimeError("Expected one backup image")
        config = archive.getmember(manifest[0]["Config"])
        if config.size > 1024 * 1024 or not config.isfile():
            raise RuntimeError("Unexpected image configuration")
        actual = (
            "sha256:" + hashlib.sha256(archive.extractfile(config).read()).hexdigest()
        )
        if actual != expected_id:
            raise RuntimeError("Backup image identity mismatch")


def prepare_folder(key, required):
    if BACKUPS.parent.resolve() != Path("/home/app") or BACKUPS.is_symlink():
        raise RuntimeError("Unexpected production backup location")
    if shutil.disk_usage(BACKUPS.parent).free < required:
        raise RuntimeError("Insufficient free space for protected production backup")
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    if BACKUPS.stat().st_mode & 0o077:
        raise RuntimeError("Production backup directory has excessive permissions")
    folder = BACKUPS / key
    folder.mkdir(mode=0o700)
    return folder


def cleanup_helper(name, key):
    if re.fullmatch(r"prod-dependency-pgdump-[a-f0-9]{12}", name) is None:
        raise RuntimeError("Unexpected backup helper name")
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "procollab.backup.key"}}',
            name,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    if result.returncode == 0 and result.stdout.decode().strip() == key:
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )


def main():
    os.umask(0o077)
    before, containers = inspect_runtime()
    major = before["postgresql_version_num"] // 10000
    if not 12 <= major <= 18:
        raise RuntimeError("Unsupported PostgreSQL backup client version")
    web = containers["web"][0]
    image_id = containers["web"][1]
    image_info = json.loads(
        read(["docker", "image", "inspect", "--format", "{{json .Size}}", image_id])
    )
    required = max(3 * 1024**3, 3 * before["database_bytes"] + 2 * image_info + RESERVE)
    key = (
        "prod-dependencies-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid4().hex[:8]
    )
    folder = prepare_folder(key, required)
    emit("PROD_BACKUP_STARTED=" + key)

    config_source = """
import json,os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','procollab.settings')
import django
django.setup()
from django.conf import settings
cfg=settings.DATABASES['default']
print(json.dumps({key:cfg.get(key,'') for key in ('NAME','USER','PASSWORD','HOST','PORT','OPTIONS')}))
"""
    config = json.loads(
        read(
            [
                "docker",
                "exec",
                "-i",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                web,
                "python",
                "-",
            ],
            source=config_source.encode(),
        )
    )
    import prod_preflight
    import base64

    expected = base64.b64decode(prod_preflight.EXPECTED_DATABASE_NAME_B64).decode()
    endpoint = json.loads(base64.b64decode(prod_preflight.EXPECTED_DATABASE_ENDPOINT_B64))
    if (
        not expected
        or config["NAME"] != expected
        or str(config.get("HOST", "")).lower() != str(endpoint.get("HOST", "")).lower()
        or str(config.get("PORT") or "5432") != str(endpoint.get("PORT") or "5432")
        or config["NAME"] != endpoint.get("NAME")
    ):
        raise RuntimeError("Unexpected production database configuration")
    options = config.get("OPTIONS") or {}
    if set(options) - {"sslmode", "connect_timeout"}:
        raise RuntimeError(
            "Production backup requires review of nonstandard connection options"
        )
    environment = dict(os.environ)
    for destination, source in (
        ("PGHOST", "HOST"),
        ("PGPORT", "PORT"),
        ("PGDATABASE", "NAME"),
        ("PGUSER", "USER"),
        ("PGPASSWORD", "PASSWORD"),
    ):
        environment[destination] = str(config[source])
    environment["PGCONNECT_TIMEOUT"] = "10"
    environment["PGSSLMODE"] = options.get("sslmode", "prefer")
    environment["PGOPTIONS"] = "-c default_transaction_read_only=on"

    native = native_clients(major)
    helper_name = "prod-dependency-pgdump-" + uuid4().hex[:12]
    image = f"postgres:{major}-alpine"
    if native:
        dump_command, restore_command = native
        client_description = "native-postgresql-" + str(major)
    else:
        pg_environment = [
            "PGHOST",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGPASSWORD",
            "PGCONNECT_TIMEOUT",
            "PGSSLMODE",
            "PGOPTIONS",
        ]
        flags = [part for name in pg_environment for part in ("--env", name)]
        dump_command = (
            [
                "docker",
                "run",
                "--rm",
                "--name",
                helper_name,
                "--label",
                "procollab.backup.key=" + key,
                "--network",
                "container:" + web,
                "--memory",
                "256m",
                "--cpus",
                "0.5",
            ]
            + flags
            + [image, "pg_dump"]
        )
        restore_command = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            image,
            "pg_restore",
            "--file=/dev/null",
        ]
        client_description = image
    emit("PROD_BACKUP_CLIENT=" + client_description)
    dump = folder / "database.dump.partial"
    try:
        guarded_archive(
            dump_command
            + [
                "--no-password",
                "--format=custom",
                "--compress=3",
                "--no-owner",
                "--no-acl",
                "--lock-wait-timeout=5s",
            ],
            dump,
            stage="pg_dump",
            environment=environment,
        )
        validate_database_archive(dump, restore_command)
    finally:
        if not native:
            cleanup_helper(helper_name, key)
    dump = dump.rename(folder / "database.dump")
    emit("PROD_DATABASE_ARCHIVE_VALIDATED=true")

    # Capture configuration privately; none of these values are written to Actions logs.
    for name, filename in (
        (".env", "runtime.env"),
        ("docker-compose.prod-ci.yml", "compose.yml"),
    ):
        source = REPO / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("Unexpected production configuration file")
        shutil.copyfile(source, folder / filename)
        os.chmod(folder / filename, 0o600)
    runtime_environment = {
        service: json.loads(
            read(["docker", "inspect", "--format", "{{json .Config.Env}}", data[0]])
        )
        for service, data in containers.items()
    }
    (folder / "container-environments.json").write_text(
        json.dumps(runtime_environment), encoding="utf8"
    )

    image_archive = folder / "runtime-image.tar.partial"
    guarded_archive(
        ["docker", "image", "save", image_id], image_archive, stage="image_save"
    )
    validate_image_archive(image_archive, image_id)
    image_archive = image_archive.rename(folder / "runtime-image.tar")
    after, after_containers = inspect_runtime()
    if containers != after_containers or before["source_sha"] != after["source_sha"]:
        raise RuntimeError(
            "Production runtime changed during backup; review the private backup"
        )
    if digest(REPO / ".env") != digest(folder / "runtime.env") or digest(
        REPO / "docker-compose.prod-ci.yml"
    ) != digest(folder / "compose.yml"):
        raise RuntimeError("Production configuration changed during backup")
    rollback_tag = "procollab-prod-dependency-rollback:" + key
    subprocess.run(
        ["docker", "tag", image_id, rollback_tag],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    files = {}
    for filename in (
        "database.dump",
        "runtime-image.tar",
        "runtime.env",
        "compose.yml",
        "container-environments.json",
    ):
        path = folder / filename
        os.chmod(path, 0o600)
        files[filename] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    manifest = {
        "complete": True,
        "key": key,
        "before": before,
        "after": after,
        "files": files,
        "rollback_tag": rollback_tag,
        "services_not_restarted": True,
        "database_restore_performed": False,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    os.chmod(folder / "manifest.json", 0o600)
    emit("PROD_BACKUP_COMPLETE=" + key)
    emit("PROD_BACKUP_DATABASE_BYTES=" + str(files["database.dump"]["bytes"]))
    emit("PROD_BACKUP_DATABASE_SHA256=" + files["database.dump"]["sha256"])
    emit("PROD_BACKUP_IMAGE_BYTES=" + str(files["runtime-image.tar"]["bytes"]))
    emit("PROD_BACKUP_IMAGE_SHA256=" + files["runtime-image.tar"]["sha256"])
    emit("PROD_SERVICES_NOT_RESTARTED=true")
    emit("PROD_DATABASE_RESTORE_PERFORMED=false")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit("PROD_BACKUP_FAILED=" + type(error).__name__)
        if isinstance(error, RuntimeError):
            emit(str(error))
        raise SystemExit(1)
