"""Изолированное подключение для миграций только DEV; runtime .env не меняется."""

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import sys


DEV_DATABASE = "procollab_db_dev"
RUNTIME_USER = "procollab_api_dev"
MAX_PAYLOAD = 16384


class MigrationSetupError(Exception):
    pass


def require_dev(database, runtime_user):
    if database != DEV_DATABASE or runtime_user != RUNTIME_USER:
        raise MigrationSetupError("Expected DEV database and DEV runtime user")


def validate_credentials(username, password):
    if not isinstance(username, str) or not username or "\0" in username:
        raise MigrationSetupError("Missing or invalid DEV migration username")
    if username == RUNTIME_USER:
        raise MigrationSetupError("Migration role must differ from runtime role")
    if not isinstance(password, str) or not password or "\0" in password:
        raise MigrationSetupError("Missing or invalid DEV migration password")


def prepare_payload(environ, output):
    require_dev(environ.get("DEV_DATABASE_NAME"), environ.get("DEV_DATABASE_USER"))
    username = environ.get("DEV_MIGRATION_DATABASE_USER")
    password = environ.get("DEV_MIGRATION_DATABASE_PASSWORD")
    validate_credentials(username, password)
    payload = base64.b64encode(
        json.dumps({"username": username, "password": password}).encode("utf-8")
    ).decode("ascii")
    if len(payload) > MAX_PAYLOAD:
        raise MigrationSetupError("DEV migration credentials payload is too large")
    output_path = environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise MigrationSetupError("GITHUB_OUTPUT is required")
    # GitHub маскирует также производное значение до передачи его SSH action.
    output.write(f"::add-mask::{payload}\n")
    output.flush()
    with open(output_path, "a", encoding="utf-8") as output_file:
        output_file.write(f"payload={payload}\n")


def decode_payload(raw):
    raw = raw.strip()
    if len(raw) > MAX_PAYLOAD:
        raise MigrationSetupError("DEV migration credentials payload is too large")
    try:
        credentials = json.loads(base64.b64decode(raw.strip(), validate=True))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise MigrationSetupError("Invalid DEV migration credentials payload") from None
    if not isinstance(credentials, dict) or set(credentials) != {"username", "password"}:
        raise MigrationSetupError("Invalid DEV migration credentials fields")
    validate_credentials(credentials["username"], credentials["password"])
    return credentials


RELATIONS_SQL = """
SELECT c.oid, c.relname, c.relkind,
       pg_has_role(current_user, c.relowner, 'USAGE')
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = 'pg_class'::regclass
        AND d.objid = c.oid AND d.deptype = 'e'
  )
ORDER BY c.relname
"""


def preflight(connection, username):
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, current_schema()")
        database, actual_user, schema = cursor.fetchone()
        if database != DEV_DATABASE or actual_user != username or schema != "public":
            raise MigrationSetupError("DEV migration connection identity mismatch")
        cursor.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
        if any(cursor.fetchone()):
            raise MigrationSetupError("DEV migration role must not be an administrator")
        cursor.execute(
            "SELECT has_schema_privilege(current_user, 'public', 'USAGE'), "
            "has_schema_privilege(current_user, 'public', 'CREATE')"
        )
        if not all(cursor.fetchone()):
            raise MigrationSetupError("DEV migration role needs USAGE/CREATE on public")
        cursor.execute(RELATIONS_SQL)
        blocked = [name for _, name, _, owned in cursor.fetchall() if not owned]
        if blocked:
            raise MigrationSetupError("Non-owned DEV relations: " + ", ".join(blocked))


def configure_defaults(connection, runtime_user):
    from psycopg2 import sql

    # Только права штатного приложения на будущие DEV-объекты этой migration-role.
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(sql.Identifier(runtime_user))
        )
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}"
            ).format(sql.Identifier(runtime_user))
        )


def check_runtime_access(connection, runtime_user):
    with connection.cursor() as cursor:
        cursor.execute(RELATIONS_SQL)
        relations = cursor.fetchall()
        for relation_id, name, kind, _ in relations:
            function = "has_sequence_privilege" if kind == "S" else "has_table_privilege"
            privileges = (
                ("USAGE", "SELECT")
                if kind == "S"
                else ("SELECT", "INSERT", "UPDATE", "DELETE")
            )
            for privilege in privileges:
                cursor.execute(
                    f"SELECT {function}(%s, %s::oid, %s)",
                    [runtime_user, relation_id, privilege],
                )
                if not cursor.fetchone()[0]:
                    raise MigrationSetupError(
                        f"DEV runtime role lacks {privilege} on {name}"
                    )


def run_migrations(credentials, check_only=False):
    require_dev(os.environ.get("DATABASE_NAME"), os.environ.get("DATABASE_USER"))
    original = {
        name: os.environ.get(name) for name in ("DATABASE_USER", "DATABASE_PASSWORD")
    }
    try:
        os.environ["DATABASE_USER"] = credentials["username"]
        os.environ["DATABASE_PASSWORD"] = credentials["password"]
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
        import django

        django.setup()
        from django.core.management import call_command
        from django.db import connection, transaction
        from django.db.migrations.executor import MigrationExecutor

        if connection.vendor != "postgresql":
            raise MigrationSetupError("DEV migration requires PostgreSQL")
        # Проверки не могут частично применить DDL или изменить permissions.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            preflight(connection, credentials["username"])
            check_runtime_access(connection, RUNTIME_USER)
            executor = MigrationExecutor(connection)
            executor.loader.check_consistent_history(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            sys.stdout.write(f"DEV migration preflight passed; pending={len(plan)}\n")
        if check_only:
            return
        with transaction.atomic():
            configure_defaults(connection, RUNTIME_USER)
        call_command("migrate", interactive=False)
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise MigrationSetupError("DEV migrations remain unapplied")
        check_runtime_access(connection, RUNTIME_USER)
        connection.close()
        sys.stdout.write("DEV migrations and runtime access check passed\n")
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-payload", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    arguments = parser.parse_args()
    credentials = None
    try:
        if arguments.prepare_payload:
            prepare_payload(os.environ, sys.stdout)
        else:
            credentials = decode_payload(sys.stdin.read(MAX_PAYLOAD + 2))
            run_migrations(credentials, arguments.check_only)
    except Exception as error:
        # Не выводим DSN/traceback, которые могут содержать credentials.
        if isinstance(error, MigrationSetupError):
            message = str(error)
            if credentials:
                message = message.replace(credentials["password"], "[redacted]")
        else:
            message = f"DEV migration failed ({type(error).__name__})"
        sys.stderr.write(message + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
