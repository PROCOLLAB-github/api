"""Prove backup/restore on a disposable GitHub-hosted VM, never on the prod host."""

import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if (
    sys.platform != "linux"
    or os.environ.get("GITHUB_ACTIONS") != "true"
    or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    or os.environ.get("SERVER_HOST")
    or os.environ.get("SERVER_PASSWORD")
):
    raise RuntimeError(
        "This fixture may run only on a secret-free disposable GitHub-hosted VM"
    )

ROOT = Path("/home/app/procollab-backend")
BACKUPS = Path("/home/app/procollab-dependency-backups")
if ROOT.exists() or BACKUPS.exists():
    raise RuntimeError("Fixture paths already exist; do not modify them")
subprocess.run(
    [
        "sudo",
        "install",
        "-d",
        "-m",
        "700",
        "-o",
        str(os.getuid()),
        "-g",
        str(os.getgid()),
        str(ROOT.parent),
        str(ROOT),
    ],
    check=True,
)
(ROOT / "procollab").mkdir()
(ROOT / "procollab/__init__.py").touch()
(ROOT / "Dockerfile").write_text(
    "FROM python:3.11-slim-bookworm\n"
    "RUN pip install --no-cache-dir Django==4.2.11 psycopg2-binary==2.9.9 redis==5.0.4\n"
    'WORKDIR /app\nCOPY procollab /app/procollab\nCMD ["sleep","infinity"]\n'
)
(ROOT / "procollab/settings.py").write_text("""
import os
SECRET_KEY='synthetic-only-secret'
INSTALLED_APPS=[]
NEXTGEN_SURFACE_ENABLED=False
DATABASES={'default':{
    'ENGINE':'django.db.backends.postgresql',
    'NAME':os.environ['DATABASE_NAME'], 'HOST':os.environ['DATABASE_HOST'],
    'PORT':'5432', 'USER':'fixture', 'PASSWORD':os.environ['DATABASE_PASSWORD']
}}
CELERY_BROKER_URL='redis://redis:6379/0'
""")
(ROOT / ".env").write_text(
    "DATABASE_NAME=procollab_backup_fixture\nDATABASE_HOST=postgres\nDATABASE_PASSWORD=synthetic-password-canary\n"
)
(ROOT / ".env").chmod(0o600)
(ROOT / ".gitignore").write_text(".env\n")
(ROOT / "docker-compose.prod-ci.yml").write_text("""
services:
  web:
    image: procollab-backup-proof:fixture
    build: .
    env_file: .env
  celerys:
    image: procollab-backup-proof:fixture
    env_file: .env
  postgres:
    image: postgres:14-alpine
    environment:
      POSTGRES_DB: procollab_backup_fixture
      POSTGRES_USER: fixture
      POSTGRES_PASSWORD: synthetic-password-canary
  redis:
    image: redis:7-alpine
""")
for args in (
    ["init"],
    ["config", "user.name", "Backup CI"],
    ["config", "user.email", "ci@example.invalid"],
    ["add", "."],
    ["commit", "-qm", "Synthetic backup fixture"],
):
    subprocess.run(["git", "-C", str(ROOT)] + args, check=True, stdout=subprocess.DEVNULL)
compose = [
    "docker",
    "compose",
    "-f",
    str(ROOT / "docker-compose.prod-ci.yml"),
    "-p",
    "prod",
]


def run(args, **kwargs):
    return subprocess.run(
        args,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
        **kwargs
    ).stdout


try:
    run(compose + ["build", "web"])
    run(compose + ["up", "-d"])
    for attempt in range(60):
        ready = subprocess.run(
            compose
            + [
                "exec",
                "-T",
                "postgres",
                "pg_isready",
                "-U",
                "fixture",
                "-d",
                "procollab_backup_fixture",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Fixture PostgreSQL did not start")
    run(
        compose
        + [
            "exec",
            "-T",
            "postgres",
            "psql",
            "-q",
            "-U",
            "fixture",
            "-d",
            "procollab_backup_fixture",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=(
            b"CREATE TABLE django_migrations(id serial PRIMARY KEY,app text,name text); "
            b"INSERT INTO django_migrations(app,name) VALUES ('synthetic','0001'); "
            b"CREATE TABLE users_backup_fixture(id int PRIMARY KEY,value text); "
            b"INSERT INTO users_backup_fixture VALUES(1,'synthetic-private-record-canary');"
        ),
    )
    import prod_preflight
    import prod_backup

    prod_preflight.EXPECTED_DATABASE_NAME_B64 = base64.b64encode(
        b"procollab_backup_fixture"
    ).decode()
    prod_backup.native_clients = lambda major: None
    with contextlib.redirect_stdout(io.StringIO()) as captured:
        prod_backup.main()
    output = captured.getvalue()
    assert (
        "synthetic-password-canary" not in output
        and "synthetic-private-record-canary" not in output
    )
    folder = next(BACKUPS.glob("prod-dependencies-*"))
    manifest = json.loads((folder / "manifest.json").read_text())
    assert (
        manifest["complete"]
        and manifest["services_not_restarted"]
        and not manifest["database_restore_performed"]
    )
    assert folder.stat().st_mode & 0o077 == 0
    for name, record in manifest["files"].items():
        path = folder / name
        assert path.stat().st_mode & 0o077 == 0
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    pg_container = run(compose + ["ps", "-q", "postgres"]).decode().strip()
    run(
        [
            "docker",
            "cp",
            str(folder / "database.dump"),
            pg_container + ":/tmp/synthetic-backup.dump",
        ]
    )
    run(
        compose
        + [
            "exec",
            "-T",
            "postgres",
            "createdb",
            "-U",
            "fixture",
            "backup_restore_fixture",
        ]
    )
    run(
        compose
        + [
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "-U",
            "fixture",
            "--dbname",
            "backup_restore_fixture",
            "--no-owner",
            "--no-acl",
            "/tmp/synthetic-backup.dump",
        ]
    )
    value = (
        run(
            compose
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-At",
                "-U",
                "fixture",
                "-d",
                "backup_restore_fixture",
                "-c",
                "SELECT value FROM users_backup_fixture WHERE id=1",
            ]
        )
        .decode()
        .strip()
    )
    assert value == "synthetic-private-record-canary"
    sys.stdout.write("DISPOSABLE_RUNNER_BACKUP_AND_RESTORE_PROOF=true\n")
    sys.stdout.write("DISPOSABLE_RUNNER_IMAGE_ARCHIVE_AND_PERMISSIONS_PROOF=true\n")
    sys.stdout.write("DISPOSABLE_RUNNER_SECRET_REDACTION_PROOF=true\n")
    sys.stdout.write("DISPOSABLE_RUNNER_SERVICES_NOT_RESTARTED_PROOF=true\n")
finally:
    subprocess.run(
        compose + ["down", "--volumes"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )
