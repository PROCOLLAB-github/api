"""Одноразовая подготовка DEV на PostgreSQL 14 двумя существующими login."""

import getpass
import os
import signal
import sys


DATABASE = "procollab_db_dev"
RUNTIME = "procollab_api_dev"
MIGRATOR = "procollab_api"


class PreparationError(Exception):
    pass


def prepare_owner(sql_text, migration_password):
    if (
        os.environ.get("DATABASE_NAME") != DATABASE
        or os.environ.get("DATABASE_USER") != RUNTIME
    ):
        raise PreparationError("Expected DEV database and runtime login")
    if not migration_password:
        raise PreparationError("Migration password is required")
    import psycopg2

    options = dict(
        host=os.environ["DATABASE_HOST"],
        port=os.environ.get("DATABASE_PORT") or "5432",
        dbname=DATABASE,
        sslmode="require",
        connect_timeout=15,
    )

    def runtime_connection():
        connection = psycopg2.connect(
            **options, user=RUNTIME, password=os.environ["DATABASE_PASSWORD"]
        )
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '15s'")
        return connection

    source = runtime_connection()
    target = None
    grant_attempted = False
    initial_membership = None
    try:
        with source.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_user, session_user, current_setting('server_version_num')"
            )
            database, user, session_user, version = cursor.fetchone()
            if (database, user, session_user) != (DATABASE, RUNTIME, RUNTIME):
                raise PreparationError("DEV runtime connection identity mismatch")
            if int(version) // 10000 != 14:
                raise PreparationError(
                    "This one-time self-role grant procedure is verified only on PostgreSQL 14"
                )
            cursor.execute("SELECT pg_try_advisory_lock(180614, 20261018)")
            if not cursor.fetchone()[0]:
                raise PreparationError("Another DEV owner preparation is running")
            cursor.execute("SELECT pg_has_role(%s, %s, 'MEMBER')", [MIGRATOR, RUNTIME])
            initial_membership = cursor.fetchone()[0]
            cursor.execute("SELECT rolinherit FROM pg_roles WHERE rolname=%s", [MIGRATOR])
            row = cursor.fetchone()
            if not row or not row[0]:
                raise PreparationError("Expected existing INHERIT migration role")
            cursor.execute(
                "SELECT c.relname,pg_get_userbyid(c.relowner),pg_has_role(%s,c.relowner,'USAGE') "
                "FROM pg_class c WHERE c.oid IN ('public.users_university'::regclass, "
                "'public.users_university_id_seq'::regclass)",
                [MIGRATOR],
            )
            relations = cursor.fetchall()
            if len(relations) != 2 or any(
                owner not in (RUNTIME, MIGRATOR) for _, owner, _ in relations
            ):
                raise PreparationError("Unexpected DEV university ownership")
            need_grant = not all(owned for _, _, owned in relations)
        # Authenticate the known migration login before granting anything.
        target = psycopg2.connect(**options, user=MIGRATOR, password=migration_password)
        target.autocommit = True
        with target.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, session_user")
            if cursor.fetchone() != (DATABASE, MIGRATOR, MIGRATOR):
                raise PreparationError("DEV migration connection identity mismatch")
        if need_grant:
            if initial_membership:
                raise PreparationError(
                    "Existing membership does not provide expected ownership privileges"
                )
            # PostgreSQL 14 permits session_user to grant membership in its own role.
            # The direction is DEV role -> migrator; DEV never receives the PROD owner role.
            grant_attempted = True
            with source.cursor() as cursor:
                cursor.execute("GRANT procollab_api_dev TO procollab_api")
        with target.cursor() as cursor:
            cursor.execute(sql_text)
            cursor.execute(
                "SELECT c.relname,pg_get_userbyid(c.relowner) FROM pg_class c "
                "WHERE c.oid IN ('public.users_university'::regclass, "
                "'public.users_university_id_seq'::regclass) ORDER BY c.relname"
            )
            owners = cursor.fetchall()
            if len(owners) != 2 or any(owner != MIGRATOR for _, owner in owners):
                raise PreparationError("Final DEV ownership verification failed")
            for function, relation, privileges in (
                (
                    "has_table_privilege",
                    "public.users_university",
                    ("SELECT", "INSERT", "UPDATE", "DELETE"),
                ),
                (
                    "has_sequence_privilege",
                    "public.users_university_id_seq",
                    ("USAGE", "SELECT", "UPDATE"),
                ),
            ):
                for privilege in privileges:
                    cursor.execute(
                        "SELECT " + function + "(%s,%s,%s)",
                        [RUNTIME, relation, privilege],
                    )
                    if not cursor.fetchone()[0]:
                        raise PreparationError(
                            "DEV runtime privilege verification failed"
                        )
    finally:
        if target is not None:
            target.close()  # Also rolls back failed/uncommitted normalization before cleanup.
        try:
            if grant_attempted:
                if source.closed:
                    source = runtime_connection()
                with source.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_has_role(%s,%s,'MEMBER')", [MIGRATOR, RUNTIME]
                    )
                    if cursor.fetchone()[0] != initial_membership:
                        cursor.execute("REVOKE procollab_api_dev FROM procollab_api")
                    cursor.execute(
                        "SELECT pg_has_role(%s,%s,'MEMBER')", [MIGRATOR, RUNTIME]
                    )
                    if cursor.fetchone()[0] != initial_membership:
                        raise PreparationError(
                            "Temporary DEV membership did not return to its initial state"
                        )
        except Exception as error:
            raise PreparationError(
                "TEMPORARY MEMBERSHIP CLEANUP NOT VERIFIED. As procollab_api_dev run: "
                "REVOKE procollab_api_dev FROM procollab_api;"
            ) from error
        finally:
            source.close()
    sys.stdout.write(
        "DEV ownership prepared; runtime access verified; no new membership remains.\n"
    )
    for name, owner in owners:
        sys.stdout.write(f"{name} owner={owner}\n")


def main():
    password = None
    try:
        if len(sys.argv) != 2:
            raise PreparationError(
                "Pass the reviewed DEV normalization SQL as the only argument"
            )
        if (
            os.environ.get("DATABASE_NAME") != DATABASE
            or os.environ.get("DATABASE_USER") != RUNTIME
        ):
            raise PreparationError("Expected DEV database and runtime login")
        password = getpass.getpass("Password for procollab_api (hidden): ")
        prepare_owner(sys.argv[1], password)
    except Exception as error:
        message = str(error)
        for secret in (password, os.environ.get("DATABASE_PASSWORD")):
            if secret:
                message = message.replace(secret, "[redacted]")
        sys.stderr.write("STOP: " + message + "\n")
        return 1
    return 0


if __name__ == "__main__":

    def interrupted(signum, frame):
        raise SystemExit("Interrupted; attempting temporary membership cleanup")

    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupted)
    raise SystemExit(main())
