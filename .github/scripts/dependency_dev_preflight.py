"""DEV-only read-only data checks and a protected, validated database backup."""

import hashlib
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

REPO = Path("/root/api")
BACKUPS = Path("/root/procollab-dependency-backups")
KEY = re.compile(r"dependency-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}")

PROBE = r"""
import hashlib, json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'procollab.settings')
import django
django.setup()
from django.db import connection, transaction
payload = {'django': django.get_version(), 'tables': {}}
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout = '60s'")
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute(
            "SELECT current_database(), current_setting('server_version_num')::int, "
            "pg_database_size(current_database())"
        )
        name, version, size = cursor.fetchone()
        if name != 'procollab_db_dev' or not 140000 <= version < 190000:
            raise RuntimeError('Unexpected DEV database or unsupported PostgreSQL version')
        payload.update(server_major=version // 10000, database_bytes=size)
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        tables = [
            row[0] for row in cursor.fetchall()
            if row[0].startswith(
                ('users_', 'projects_', 'partner_programs_', 'project_rates_', 'files_')
            )
        ]
        for table in tables:
            cursor.execute(
                'SELECT a.attname FROM pg_index i JOIN pg_attribute a '
                'ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) '
                'WHERE i.indrelid=to_regclass(%s) AND i.indisprimary ORDER BY a.attnum',
                [table],
            )
            primary = [row[0] for row in cursor.fetchall()]
            if not primary:
                raise RuntimeError('Missing primary key in a protected table')
            identity = 'jsonb_build_array(' + ','.join(
                't.' + connection.ops.quote_name(key) for key in primary
            ) + ')::text'
            record = "(to_jsonb(t) - 'last_activity' - 'last_login' - 'datetime_updated')::text"
            hash_sql = lambda expression: "encode(sha256(convert_to(" + expression + ", 'UTF8')), 'hex')"
            cursor.execute(
                'SELECT ' + hash_sql(identity) + ',' + hash_sql(record)
                + ' FROM ' + connection.ops.quote_name(table) + ' t'
            )
            records = {}
            while True:
                batch = cursor.fetchmany(500)
                if not batch:
                    break
                for identity, record_hash in batch:
                    records[identity] = record_hash
            payload['tables'][table] = records
print(json.dumps(payload, ensure_ascii=False))
"""

SERVICES = r"""
import base64, json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'procollab.settings')
import django
django.setup()
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.validators import validate_email
import requests
from files.service import SelectelSwiftStorage
result = {'cdn_ok': False, 'email_attempted': False, 'email_accepted': False}
original_request = requests.sessions.Session.request
def bounded(self, *args, **kwargs):
    kwargs.setdefault('timeout', 15)
    return original_request(self, *args, **kwargs)
requests.sessions.Session.request = bounded
try:
    token = SelectelSwiftStorage._get_auth_token()
    response = requests.head(
        settings.SELECTEL_SWIFT_URL, headers={'X-Auth-Token': token}, timeout=15
    )
    result['cdn_status'] = response.status_code
    result['cdn_ok'] = response.status_code in (200, 204)
    if not result['cdn_ok']:
        raise RuntimeError('CDN HEAD check failed')
    recipient = base64.b64decode(CONTROL_RECIPIENT_B64, validate=True).decode().strip()
    if recipient:
        validate_email(recipient)
        message = EmailMessage(
            'Проверка PROCOLLAB dev после обновления',
            'Контрольное письмо для проверки доставки после обновления '
            'серверных зависимостей PROCOLLAB dev. Действий с вашей стороны не требуется.',
            settings.EMAIL_USER, [recipient],
        )
        result['email_attempted'] = True
        result['email_accepted'] = message.send(fail_silently=False) == 1
        status = getattr(message, 'anymail_status', None)
        result['email_status'] = sorted(getattr(status, 'status', set()))
except Exception as error:
    result['error_type'] = type(error).__name__
print(json.dumps(result))
"""

PROGRAM_COMPARE = r"""
import base64, json, os, re
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'procollab.settings')
import django
django.setup()
from django.db import connection, transaction
payload = json.loads(base64.b64decode(ARCHIVE_PROGRAM_PAYLOAD))
def decode_copy(value):
    if value == r'\N':
        return None
    replacements = {b'b': b'\b', b'f': b'\f', b'n': b'\n', b'r': b'\r', b't': b'\t', b'v': b'\v'}
    def replace(match):
        value = match.group(1)
        if value[:1] in b'01234567':
            return bytes([int(value, 8)])
        if value.startswith(b'x'):
            return bytes([int(value[1:], 16)])
        return replacements.get(value, value)
    return re.sub(rb'\\([0-7]{1,3}|x[0-9a-fA-F]{1,2}|.)', replace, value.encode()).decode()
result = {'differences': [], 'archive_identities': []}
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout = '60s'")
        cursor.execute('SELECT current_database()')
        if cursor.fetchone()[0] != 'procollab_db_dev':
            raise RuntimeError('Unexpected database')
        cursor.execute(
            'SELECT attname, pg_catalog.format_type(atttypid, atttypmod) '
            "FROM pg_attribute WHERE attrelid='public.partner_programs_partnerprogram'::regclass "
            'AND attnum>0 AND NOT attisdropped ORDER BY attnum'
        )
        columns = cursor.fetchall()
        if set(payload['columns']) != {name for name, kind in columns}:
            raise RuntimeError('Program archive schema mismatch')
        row_expression = 'ROW(' + ','.join('%s::' + kind for name, kind in columns)
        row_expression += ')::public.partner_programs_partnerprogram'
        query = (
            'WITH archived AS (SELECT (' + row_expression + ').*) '
            'SELECT a.id, c.id IS NOT NULL, ARRAY('
            'SELECT field FROM jsonb_object_keys(to_jsonb(c)) AS keys(field) '
            "WHERE field NOT IN ('datetime_updated','last_activity','last_login') "
            'AND (to_jsonb(c)->field) IS DISTINCT FROM (to_jsonb(a)->field)), '
            "encode(sha256(convert_to(jsonb_build_array(a.id)::text,'UTF8')),'hex') "
            'FROM archived a LEFT JOIN public.partner_programs_partnerprogram c USING(id)'
        )
        for line in payload['copy_data'].split('\n'):
            if not line:
                continue
            values = [decode_copy(value) for value in line.split('\t')]
            if len(values) != len(payload['columns']):
                raise RuntimeError('Program archive column count mismatch')
            record = dict(zip(payload['columns'], values))
            cursor.execute(query, [record[name] for name, kind in columns])
            identity, present, changed, fingerprint = cursor.fetchone()
            result['archive_identities'].append(fingerprint)
            if changed or not present:
                result['differences'].append({'id': identity, 'present': present, 'fields': changed})
print(json.dumps(result))
"""


def emit(message, *, file=sys.stdout, flush=True):
    file.write(message + "\n")
    if flush:
        file.flush()


def command(args, stage="check", **kwargs):
    try:
        return subprocess.run(args, check=True, stderr=subprocess.PIPE, **kwargs)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        message = error.stderr or b""
        if isinstance(message, str):
            message = message.encode()
        message = message.lower()
        category = "command_failure"
        for marker, label in (
            (b"permission denied", "permission_denied"),
            (b"authentication failed", "authentication_failed"),
            (b"too many requests", "registry_rate_limit"),
            (b"toomanyrequests", "registry_rate_limit"),
            (b"could not translate host", "hostname_resolution"),
            (b"connection refused", "connection_refused"),
            (b"timeout", "timeout"),
            (b"server version", "client_server_version"),
        ):
            if marker in message:
                category = label
                break
        if isinstance(error, subprocess.TimeoutExpired):
            category = "timeout"
        code = getattr(error, "returncode", "timeout")
        raise RuntimeError(
            f"DEV command failed: stage={stage}, code={code}, category={category}"
        ) from None


def output(args, **kwargs):
    return command(args, stdout=subprocess.PIPE, **kwargs).stdout


def inspect_container(container):
    value = json.loads(output(["docker", "inspect", container]))[0]
    labels = value["Config"].get("Labels", {})
    paths = labels.get("com.docker.compose.project.config_files", "").split(",")
    if str(REPO / "docker-compose.dev-ci.yml") not in paths:
        raise RuntimeError("Container does not belong to the DEV compose configuration")
    return value


def snapshot(web):
    return json.loads(
        output(
            ["docker", "exec", "-i", web, "python", "-"],
            input=PROBE.encode(),
            timeout=180,
        )
    )


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate_archive(path, restore_command):
    # The child inherits the OS file position, so do not buffer the header read.
    with path.open("rb", buffering=0) as handle:
        if handle.read(5) != b"PGDMP":
            raise RuntimeError("Invalid backup archive")
        handle.seek(0)
        command(
            restore_command,
            stdin=handle,
            stdout=subprocess.DEVNULL,
            timeout=600,
            stage="pg_restore_validation",
        )


def native_client(major):
    candidates = [
        (
            Path(f"/usr/lib/postgresql/{major}/bin/pg_dump"),
            Path(f"/usr/lib/postgresql/{major}/bin/pg_restore"),
        )
    ]
    dump_path, restore_path = shutil.which("pg_dump"), shutil.which("pg_restore")
    if dump_path and restore_path:
        candidates.append((Path(dump_path), Path(restore_path)))
    for dump_path, restore_path in candidates:
        if not dump_path.is_file() or not restore_path.is_file():
            continue
        versions = []
        for executable in (dump_path, restore_path):
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
        if versions[0] == versions[1] and major <= versions[0] <= 18:
            return str(dump_path), str(restore_path), versions[0]
    return None


def parse_program_archive(source):
    lines = source.split("\n")
    pattern = re.compile(
        r"^COPY public\.partner_programs_partnerprogram \(([^)]+)\) FROM stdin;$"
    )
    for index, line in enumerate(lines):
        match = pattern.fullmatch(line)
        if match is None:
            continue
        columns = [name.strip().strip('"') for name in match.group(1).split(",")]
        if not all(re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in columns):
            raise RuntimeError("Unexpected program archive columns")
        for end in range(index + 1, len(lines)):
            if lines[end] == r"\.":
                start = index + 1
                return {
                    "columns": columns,
                    "copy_data": "\n".join(lines[start:end]),
                }
        raise RuntimeError("Incomplete program COPY data")
    raise RuntimeError("Program COPY data not found")


def compare_program_archive(web, dump, major):
    native = native_client(major)
    if native is None:
        raise RuntimeError("Native pg_restore required for program comparison")
    restored = output(
        [
            native[1],
            "--data-only",
            "--table=partner_programs_partnerprogram",
            "--file=-",
            str(dump),
        ],
        timeout=120,
        stage="program_archive_read",
    )
    payload = parse_program_archive(restored.decode())
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    source = "ARCHIVE_PROGRAM_PAYLOAD = " + repr(encoded) + "\n" + PROGRAM_COMPARE
    result = json.loads(
        output(
            ["docker", "exec", "-i", web, "python", "-"],
            input=source.encode(),
            timeout=180,
            stage="program_archive_comparison",
        )
    )
    emit("PROGRAM_ARCHIVE_FIELD_DIFF=" + json.dumps(result["differences"]))
    return result


def check_services(web):
    encoded = os.environ.get("DEPENDENCY_TEST_RECIPIENT_B64", "")
    recipient = base64.b64decode(encoded, validate=True).decode().strip()
    receipt = None
    previous = False
    if recipient:
        identity = hashlib.sha256(recipient.lower().encode()).hexdigest()
        receipt = BACKUPS / ("mail-test-django-5.2.18-" + identity + ".json")
        if receipt.exists():
            state = json.loads(receipt.read_text(encoding="utf8"))
            if not state.get("accepted"):
                raise RuntimeError(
                    "Prior control-email outcome is uncertain; manual review required"
                )
            encoded = ""
            previous = True
        else:
            with receipt.open("x", encoding="utf8") as handle:
                json.dump({"attempted": True, "accepted": False}, handle)
    source = "CONTROL_RECIPIENT_B64 = " + repr(encoded) + "\n" + SERVICES
    result = json.loads(
        output(
            ["docker", "exec", "-i", web, "python", "-"],
            input=source.encode(),
            timeout=120,
            stage="external_service_checks",
        )
    )
    if receipt is not None and not previous:
        if result.get("email_accepted"):
            receipt.write_text(
                json.dumps({"attempted": True, "accepted": True}), encoding="utf8"
            )
        elif not result.get("email_attempted"):
            receipt.unlink()
    emit("CDN_AUTH_AND_HEAD_OK=" + str(bool(result.get("cdn_ok"))).lower())
    emit(
        "CONTROL_EMAIL_ACCEPTED="
        + str(previous or bool(result.get("email_accepted"))).lower()
    )
    if result.get("error_type"):
        emit("EXTERNAL_SERVICE_ERROR_TYPE=" + result["error_type"])
    if not result.get("cdn_ok") or (
        recipient and not previous and not result.get("email_accepted")
    ):
        raise RuntimeError(
            "External service acceptance failed; inspect safe status markers"
        )


def main():
    phase = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else ""
    if phase not in ("backup", "verify") or REPO.resolve() != REPO:
        raise RuntimeError("Invalid operation or repository location")
    os.umask(0o077)
    os.chdir(REPO)
    web = output(
        ["docker", "compose", "-f", "docker-compose.dev-ci.yml", "ps", "-q", "web"],
        text=True,
    ).strip()
    worker = output(
        ["docker", "compose", "-f", "docker-compose.dev-ci.yml", "ps", "-q", "celerys"],
        text=True,
    ).strip()
    if not re.fullmatch(r"[a-f0-9]{12,64}", web) or not re.fullmatch(
        r"[a-f0-9]{12,64}", worker
    ):
        raise RuntimeError("Expected exactly one running DEV web and worker")
    runtime = inspect_container(web)
    worker_runtime = inspect_container(worker)
    if runtime["Image"] != worker_runtime["Image"]:
        raise RuntimeError("DEV web and worker use different images")
    current = snapshot(web)
    emit("POSTGRESQL_MAJOR=" + str(current["server_major"]), flush=True)
    emit("DJANGO_RUNTIME=" + current["django"], flush=True)

    if phase == "backup":
        required = max(2 * 1024**3, current["database_bytes"] * 2 + 512 * 1024**2)
        if shutil.disk_usage("/root").free < required:
            raise RuntimeError(
                "Insufficient free space for a protected DEV backup and rollout"
            )
        key = (
            "dependency-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid4().hex[:8]
        )
        BACKUPS.mkdir(mode=0o700, exist_ok=True)
        folder = BACKUPS / key
        folder.mkdir(mode=0o700)
        dump = folder / "database.dump"
        environment_script = (
            "import json,os; print(json.dumps({k:os.environ[k] for k in "
            '("DATABASE_HOST","DATABASE_PORT","DATABASE_NAME",'
            '"DATABASE_USER","DATABASE_PASSWORD")}))'
        )
        config = json.loads(
            output(["docker", "exec", web, "python", "-c", environment_script])
        )
        if config["DATABASE_NAME"] != "procollab_db_dev":
            raise RuntimeError("Unexpected DEV database configuration")
        environment = dict(os.environ)
        for destination, source in (
            ("PGHOST", "DATABASE_HOST"),
            ("PGPORT", "DATABASE_PORT"),
            ("PGDATABASE", "DATABASE_NAME"),
            ("PGUSER", "DATABASE_USER"),
            ("PGPASSWORD", "DATABASE_PASSWORD"),
        ):
            environment[destination] = config[source]
        client = "postgres:" + str(current["server_major"]) + "-alpine"
        container_name = "dependency-backup-" + uuid4().hex[:12]
        native = native_client(current["server_major"])
        if native:
            dump_command = [native[0]]
            restore_command = [native[1], "--file=/dev/null"]
            emit("BACKUP_CLIENT=native-postgresql-" + str(native[2]))
        else:
            dump_command = [
                "docker",
                "run",
                "--rm",
                "--name",
                container_name,
                "--network",
                "container:" + web,
                "--env",
                "PGHOST",
                "--env",
                "PGPORT",
                "--env",
                "PGDATABASE",
                "--env",
                "PGUSER",
                "--env",
                "PGPASSWORD",
                client,
                "pg_dump",
            ]
            restore_command = [
                "docker",
                "run",
                "--rm",
                "-i",
                client,
                "pg_restore",
                "--file=/dev/null",
            ]
            emit("BACKUP_CLIENT=" + client)
        emit("PG_DUMP_START=true")
        try:
            with dump.open("xb") as handle:
                command(
                    dump_command
                    + [
                        "--no-password",
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        "--lock-wait-timeout=30s",
                    ],
                    env=environment,
                    stdout=handle,
                    timeout=600,
                    stage="pg_dump",
                )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        emit("PG_DUMP_BYTES=" + str(dump.stat().st_size))
        validate_archive(dump, restore_command)
        rollback = "procollab-dependency-rollback:" + key
        command(["docker", "tag", runtime["Image"], rollback], stdout=subprocess.DEVNULL)
        shutil.copyfile(REPO / ".env", folder / "runtime.env")
        os.chmod(folder / "runtime.env", 0o600)
        metadata = {
            "snapshot": current,
            "image_id": runtime["Image"],
            "image": runtime["Config"]["Image"],
            "rollback_tag": rollback,
            "source_sha": output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "dump_sha256": digest(dump),
            "dump_bytes": dump.stat().st_size,
        }
        (folder / "manifest.json").write_text(json.dumps(metadata), encoding="utf8")
        emit("BACKUP_KEY=" + key)
        emit("BACKUP_BYTES=" + str(metadata["dump_bytes"]))
        emit("BACKUP_SHA256=" + metadata["dump_sha256"])
        emit("ROLLBACK_IMAGE=" + rollback)
    else:
        if KEY.fullmatch(key) is None:
            raise RuntimeError("Invalid backup key")
        folder = BACKUPS / key
        if folder.resolve().parent != BACKUPS.resolve():
            raise RuntimeError("Invalid backup location")
        before = json.loads((folder / "manifest.json").read_text(encoding="utf8"))
        if digest(folder / "database.dump") != before["dump_sha256"]:
            raise RuntimeError("Backup digest mismatch")
        removed, changed = {}, {}
        for table, records in before["snapshot"]["tables"].items():
            after = current["tables"].get(table, {})
            missing = set(records) - set(after)
            different = [
                identity
                for identity in set(records) & set(after)
                if records[identity] != after[identity]
            ]
            if missing:
                removed[table] = len(missing)
            if different:
                changed[table] = len(different)
        emit("REMOVED_EXISTING_RECORDS=" + json.dumps(removed))
        emit("CHANGED_EXISTING_RECORDS=" + json.dumps(changed))
        table = "partner_programs_partnerprogram"
        if table in changed:
            compared = compare_program_archive(
                web, folder / "database.dump", current["server_major"]
            )
            if not compared["differences"] and set(compared["archive_identities"]) == set(
                before["snapshot"]["tables"][table]
            ):
                changed.pop(table)
                emit("PROGRAM_ARCHIVE_CONTENT_MATCH=true")
        check_services(web)
        if removed or changed:
            raise RuntimeError("Existing DEV records changed; inspect before continuing")
        emit("EXISTING_DEV_DATA_PRESERVED=true")
        emit("CURRENT_IMAGE=" + runtime["Config"]["Image"])
    emit(
        "PROTECTED_TABLE_COUNTS="
        + json.dumps({name: len(rows) for name, rows in current["tables"].items()})
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit("DEV_DEPENDENCY_PREFLIGHT_FAILED=" + type(error).__name__, file=sys.stderr)
        if isinstance(error, RuntimeError):
            emit(str(error), file=sys.stderr)
        raise SystemExit(1)
