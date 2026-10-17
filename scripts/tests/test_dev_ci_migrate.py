"""Контракт credentials и реальные DDL/default-privileges на изолированном PostgreSQL."""

import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "dev_ci_migrate.py"
SPEC = importlib.util.spec_from_file_location("dev_ci_migrate", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PREP_SPEC = importlib.util.spec_from_file_location(
    "dev_ci_prepare_owner", ROOT / "scripts/dev_ci_prepare_owner.py"
)
PREPARATION = importlib.util.module_from_spec(PREP_SPEC)
PREP_SPEC.loader.exec_module(PREPARATION)
RUNTIME = "procollab_api_dev"
MIGRATOR = "procollab_api"
PASSWORD = "ci-only 'quoted' \"double\" $() `literal` \\ newline\nпароль"


def payload(username=MIGRATOR, password=PASSWORD):
    return base64.b64encode(
        json.dumps({"username": username, "password": password}).encode("utf-8")
    ).decode("ascii")


class CredentialsTests(unittest.TestCase):
    def test_owner_preparation_rejects_non_dev_before_connecting(self):
        with mock.patch.dict(
            os.environ, DATABASE_NAME="not_dev", DATABASE_USER=RUNTIME
        ), mock.patch("psycopg2.connect") as connect:
            with self.assertRaises(PREPARATION.PreparationError):
                PREPARATION.prepare_owner("", PASSWORD)
        connect.assert_not_called()

    def test_owner_preparation_error_redacts_both_passwords(self):
        output = io.StringIO()
        with mock.patch.dict(
            os.environ,
            DATABASE_NAME="procollab_db_dev",
            DATABASE_USER=RUNTIME,
            DATABASE_PASSWORD="runtime-secret",
        ), mock.patch.object(sys, "argv", ["prepare", "SQL"]), mock.patch(
            "getpass.getpass", return_value=PASSWORD
        ), mock.patch.object(
            PREPARATION,
            "prepare_owner",
            side_effect=RuntimeError(PASSWORD + " runtime-secret"),
        ), mock.patch.object(
            sys, "stderr", output
        ):
            self.assertEqual(PREPARATION.main(), 1)
        self.assertNotIn(PASSWORD, output.getvalue())
        self.assertNotIn("runtime-secret", output.getvalue())

    def test_special_characters_round_trip_and_masked_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "github-output"
            environment = {
                "DEV_DATABASE_NAME": "procollab_db_dev",
                "DEV_DATABASE_USER": RUNTIME,
                "DEV_MIGRATION_DATABASE_USER": MIGRATOR,
                "DEV_MIGRATION_DATABASE_PASSWORD": PASSWORD,
                "GITHUB_OUTPUT": str(target),
            }
            output = io.StringIO()
            MODULE.prepare_payload(environment, output)
            encoded = target.read_text(encoding="utf-8").strip().split("=", 1)[1]
            self.assertEqual(
                MODULE.decode_payload(encoded),
                {"username": MIGRATOR, "password": PASSWORD},
            )
            self.assertEqual(output.getvalue(), f"::add-mask::{encoded}\n")
            self.assertNotIn(PASSWORD, output.getvalue())

    def test_missing_secret_stops_before_any_output(self):
        output = io.StringIO()
        with self.assertRaises(MODULE.MigrationSetupError):
            MODULE.prepare_payload(
                {
                    "DEV_DATABASE_NAME": "procollab_db_dev",
                    "DEV_DATABASE_USER": RUNTIME,
                    "DEV_MIGRATION_DATABASE_USER": MIGRATOR,
                },
                output,
            )
        self.assertEqual(output.getvalue(), "")

    def test_wrong_database_is_rejected(self):
        with self.assertRaises(MODULE.MigrationSetupError):
            MODULE.require_dev("procollab_db", RUNTIME)

    def test_runtime_role_cannot_be_migration_role(self):
        with self.assertRaises(MODULE.MigrationSetupError):
            MODULE.decode_payload(payload(RUNTIME))

    def test_malformed_or_oversized_payload_is_rejected(self):
        for encoded in ("not base64", "a" * (MODULE.MAX_PAYLOAD + 1)):
            with self.subTest(encoded_length=len(encoded)):
                with self.assertRaises(MODULE.MigrationSetupError):
                    MODULE.decode_payload(encoded)

    def test_payload_cannot_override_host_or_database(self):
        raw = json.dumps(
            {
                "username": MIGRATOR,
                "password": PASSWORD,
                "DATABASE_HOST": "untrusted.example",
            }
        ).encode()
        with self.assertRaises(MODULE.MigrationSetupError):
            MODULE.decode_payload(base64.b64encode(raw).decode())

    def test_environment_is_restored_after_setup_failure(self):
        fake_django = mock.Mock()
        fake_django.setup.side_effect = RuntimeError("injected failure")
        initial = {
            "DATABASE_NAME": "procollab_db_dev",
            "DATABASE_USER": RUNTIME,
            "DATABASE_PASSWORD": "runtime-only",
        }
        with mock.patch.dict(os.environ, initial), mock.patch.dict(
            sys.modules, {"django": fake_django}
        ):
            with self.assertRaises(RuntimeError):
                MODULE.run_migrations({"username": MIGRATOR, "password": PASSWORD})
            self.assertEqual(os.environ["DATABASE_USER"], RUNTIME)
            self.assertEqual(os.environ["DATABASE_PASSWORD"], "runtime-only")

    def test_unexpected_error_does_not_disclose_secret_or_traceback(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", [str(HELPER)]), mock.patch.object(
            sys, "stdin", io.StringIO(payload())
        ), mock.patch.object(sys, "stderr", output), mock.patch.object(
            MODULE, "run_migrations", side_effect=RuntimeError(PASSWORD)
        ):
            self.assertEqual(MODULE.main(), 1)
        self.assertNotIn(PASSWORD, output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        self.assertIn("RuntimeError", output.getvalue())


@unittest.skipUnless(
    os.environ.get("RUN_DEV_MIGRATION_PG_TESTS") == "1",
    "Requires an explicitly enabled disposable PostgreSQL cluster",
)
class PostgreSQLMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql

        cls.sql = sql
        cls.port = os.environ.get("MIGRATION_TEST_PORT", "55442")
        cls.admin_user = os.environ.get("MIGRATION_TEST_ADMIN_USER", "dev_ci_test_admin")
        if not cls.admin_user.startswith("dev_ci_test_"):
            raise RuntimeError("Tests require a dedicated disposable admin role")
        cls.admin = psycopg2.connect(
            host="127.0.0.1",
            port=cls.port,
            dbname="postgres",
            user=cls.admin_user,
            password=os.environ.get("MIGRATION_TEST_ADMIN_PASSWORD", ""),
            connect_timeout=10,
        )
        cls.admin.autocommit = True
        with cls.admin.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname='procollab_db_dev'")
            if cursor.fetchone():
                raise RuntimeError("Refusing to replace an existing database")
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname IN (%s,%s)", [RUNTIME, MIGRATOR]
            )
            if cursor.fetchone():
                raise RuntimeError("Refusing to alter existing database roles")
            for role in (RUNTIME, MIGRATOR):
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD %s "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role)),
                    [PASSWORD],
                )

    @classmethod
    def tearDownClass(cls):
        with cls.admin.cursor() as cursor:
            for role in (RUNTIME, MIGRATOR):
                cursor.execute(
                    cls.sql.SQL("DROP ROLE {}").format(cls.sql.Identifier(role))
                )
        cls.admin.close()

    def setUp(self):
        import psycopg2

        with self.admin.cursor() as cursor:
            cursor.execute(
                self.sql.SQL("CREATE DATABASE procollab_db_dev OWNER {}").format(
                    self.sql.Identifier(RUNTIME)
                )
            )
        self.created_database = True
        self.database = psycopg2.connect(
            host="127.0.0.1",
            port=self.port,
            dbname="procollab_db_dev",
            user=self.admin_user,
            password=os.environ.get("MIGRATION_TEST_ADMIN_PASSWORD", ""),
        )
        self.database.autocommit = True
        with self.database.cursor() as cursor:
            cursor.execute(
                self.sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                    self.sql.Identifier(MIGRATOR)
                )
            )
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        fixture = Path(self.directory.name)
        app = fixture / "probe_app"
        (app / "migrations").mkdir(parents=True)
        (app / "__init__.py").write_text("", encoding="utf-8")
        (app / "migrations" / "__init__.py").write_text("", encoding="utf-8")
        (app / "models.py").write_text(
            "from django.db import models\n"
            "class Probe(models.Model):\n"
            "    name = models.CharField(max_length=32)\n",
            encoding="utf-8",
        )
        (app / "migrations" / "0001_initial.py").write_text(
            "from django.db import migrations, models\n"
            "class Migration(migrations.Migration):\n"
            "    initial = True\n    dependencies = []\n"
            "    operations = [migrations.CreateModel(name='Probe', fields=["
            "('id', models.AutoField(primary_key=True)),"
            "('name', models.CharField(max_length=32))])]\n",
            encoding="utf-8",
        )
        (fixture / "role_test_settings.py").write_text(
            "import os\nSECRET_KEY='isolated-tests-only'\nDEBUG=False\n"
            "INSTALLED_APPS=['django.contrib.contenttypes','probe_app']\n"
            "DEFAULT_AUTO_FIELD='django.db.models.AutoField'\n"
            "DATABASES={'default':{'ENGINE':'django.db.backends.postgresql',"
            "'NAME':os.environ['DATABASE_NAME'],'USER':os.environ['DATABASE_USER'],"
            "'PASSWORD':os.environ['DATABASE_PASSWORD'],'HOST':'127.0.0.1',"
            "'PORT':os.environ['DATABASE_PORT']}}\n",
            encoding="utf-8",
        )
        self.environment = dict(
            os.environ,
            PYTHONPATH=str(fixture),
            DJANGO_SETTINGS_MODULE="role_test_settings",
            DATABASE_NAME="procollab_db_dev",
            DATABASE_USER=RUNTIME,
            DATABASE_PASSWORD=PASSWORD,
            DATABASE_PORT=self.port,
        )
        seeded = subprocess.run(
            [
                sys.executable,
                "-m",
                "django",
                "migrate",
                "contenttypes",
                "0001",
                "--noinput",
            ],
            env=dict(self.environment, DATABASE_USER=MIGRATOR),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(seeded.returncode, 0, seeded.stderr)
        with self.database.cursor() as cursor:
            cursor.execute(
                self.sql.SQL(
                    "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}"
                ).format(self.sql.Identifier(RUNTIME))
            )
            cursor.execute(
                self.sql.SQL(
                    "GRANT USAGE,SELECT,UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}"
                ).format(self.sql.Identifier(RUNTIME))
            )

    def tearDown(self):
        if hasattr(self, "database"):
            self.database.close()
        if getattr(self, "created_database", False):
            with self.admin.cursor() as cursor:
                cursor.execute("DROP DATABASE procollab_db_dev WITH (FORCE)")

    def run_helper(self, *arguments, username=MIGRATOR):
        password = (
            PASSWORD
            if username == MIGRATOR
            else (
                os.environ.get("MIGRATION_TEST_ADMIN_PASSWORD")
                or "ci-only-disposable-password"
            )
        )
        return subprocess.run(
            [sys.executable, str(HELPER), *arguments],
            input=payload(username, password),
            env=self.environment,
            cwd=self.directory.name,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def assert_still_pending(self):
        with self.database.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM django_migrations")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT count(*) FROM pg_default_acl")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT to_regclass('probe_app_probe')")
            self.assertIsNone(cursor.fetchone()[0])

    def test_runtime_role_cannot_apply_pending_ddl(self):
        result = subprocess.run(
            [sys.executable, "-m", "django", "migrate", "--noinput"],
            env=self.environment,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be owner", result.stderr)
        self.assert_still_pending()

    def test_owner_migrates_and_runtime_can_write_new_table_and_sequence(self):
        import psycopg2

        env_path = Path(self.directory.name) / ".env"
        env_path.write_text("DATABASE_USER=procollab_api_dev\n", encoding="utf-8")
        before = env_path.read_bytes()
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(PASSWORD, result.stdout + result.stderr)
        self.assertEqual(env_path.read_bytes(), before)
        with psycopg2.connect(
            host="127.0.0.1",
            port=self.port,
            dbname="procollab_db_dev",
            user=RUNTIME,
            password=PASSWORD,
        ) as runtime:
            with runtime.cursor() as cursor:
                cursor.execute("SELECT current_user")
                self.assertEqual(cursor.fetchone()[0], RUNTIME)
                cursor.execute(
                    "INSERT INTO probe_app_probe(name) VALUES('first') RETURNING id"
                )
                self.assertGreater(cursor.fetchone()[0], 0)
                cursor.execute("UPDATE probe_app_probe SET name='second'")
                cursor.execute("SELECT name FROM probe_app_probe")
                self.assertEqual(cursor.fetchone()[0], "second")
                cursor.execute("DELETE FROM probe_app_probe")
        repeated = self.run_helper()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("pending=0", repeated.stdout)
        runtime_check = subprocess.run(
            [sys.executable, "-m", "django", "migrate", "--check"],
            env=self.environment,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(runtime_check.returncode, 0, runtime_check.stderr)

    def test_mixed_ownership_fails_before_ddl_and_default_privileges(self):
        with self.database.cursor() as cursor:
            cursor.execute("CREATE TABLE users_university(id serial PRIMARY KEY)")
            cursor.execute(
                self.sql.SQL("ALTER TABLE users_university OWNER TO {}").format(
                    self.sql.Identifier(RUNTIME)
                )
            )
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("users_university", result.stderr)
        self.assertNotIn(PASSWORD, result.stdout + result.stderr)
        self.assert_still_pending()

    def test_check_only_does_not_change_schema_or_defaults(self):
        result = self.run_helper("--check-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_still_pending()

    def test_admin_credentials_are_rejected(self):
        result = self.run_helper(username=self.admin_user)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not be an administrator", result.stderr)
        self.assert_still_pending()

    def test_university_owner_normalization_preserves_data_and_runtime_access(self):
        import psycopg2

        with self.database.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE users_university(id serial PRIMARY KEY, name text)"
            )
            cursor.execute(
                "INSERT INTO users_university(name) VALUES('existing university')"
            )
            cursor.execute(
                self.sql.SQL("ALTER TABLE users_university OWNER TO {}").format(
                    self.sql.Identifier(RUNTIME)
                )
            )
            cursor.execute(
                (
                    ROOT / "docs/operations/dev-migration-role-university-owner.sql"
                ).read_text(encoding="utf-8")
            )
            cursor.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class "
                "WHERE oid='users_university'::regclass"
            )
            self.assertEqual(cursor.fetchone()[0], MIGRATOR)
        with psycopg2.connect(
            host="127.0.0.1",
            port=self.port,
            dbname="procollab_db_dev",
            user=RUNTIME,
            password=PASSWORD,
        ) as runtime:
            with runtime.cursor() as cursor:
                cursor.execute("SELECT name FROM users_university")
                self.assertEqual(cursor.fetchall(), [("existing university",)])
                cursor.execute(
                    "INSERT INTO users_university(name) VALUES('new university') RETURNING id"
                )
                self.assertEqual(cursor.fetchone()[0], 2)
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_database_is_rejected_before_connecting(self):
        result = subprocess.run(
            [sys.executable, str(HELPER)],
            input=payload(),
            env=dict(
                self.environment, DATABASE_NAME="not_dev", DATABASE_HOST="invalid.example"
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected DEV database", result.stderr)
        self.assert_still_pending()

    def test_normalizer_refuses_non_dev_database(self):
        import psycopg2

        with self.admin.cursor() as cursor:
            try:
                with self.assertRaises(psycopg2.Error) as captured:
                    cursor.execute(
                        (
                            ROOT
                            / "docs/operations/dev-migration-role-university-owner.sql"
                        ).read_text(encoding="utf-8")
                    )
                self.assertIn("Only procollab_db_dev", str(captured.exception))
            finally:
                cursor.execute("ROLLBACK")
        self.assert_still_pending()

    def seed_runtime_university(self):
        with self.database.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE users_university(id SERIAL PRIMARY KEY,name TEXT)"
            )
            cursor.execute(
                "INSERT INTO users_university(name) VALUES('preserve this row')"
            )
            cursor.execute("ALTER TABLE users_university OWNER TO procollab_api_dev")

    def prepare_with_existing_logins(self, sql_text=None):
        import psycopg2

        connect = psycopg2.connect

        def fixture_connect(**kwargs):
            self.assertEqual(kwargs["host"], "127.0.0.1")
            self.assertEqual(str(kwargs["port"]), str(self.port))
            self.assertEqual(kwargs["dbname"], "procollab_db_dev")
            kwargs["sslmode"] = "disable"  # Disposable loopback fixture only.
            return connect(**kwargs)

        if sql_text is None:
            sql_text = (
                ROOT / "docs/operations/dev-migration-role-university-owner.sql"
            ).read_text(encoding="utf-8")
        with mock.patch.dict(
            os.environ,
            DATABASE_NAME="procollab_db_dev",
            DATABASE_USER=RUNTIME,
            DATABASE_PASSWORD=PASSWORD,
            DATABASE_HOST="127.0.0.1",
            DATABASE_PORT=str(self.port),
        ), mock.patch("psycopg2.connect", side_effect=fixture_connect):
            PREPARATION.prepare_owner(sql_text, PASSWORD)

    def require_postgres14(self):
        if self.database.server_version // 10000 != 14:
            self.skipTest("Self-role grant is a PostgreSQL 14 one-time procedure")

    def assert_no_temporary_membership(self):
        with self.database.cursor() as cursor:
            cursor.execute(
                "SELECT pg_has_role('procollab_api','procollab_api_dev','MEMBER')"
            )
            self.assertFalse(cursor.fetchone()[0])
            cursor.execute(
                "SELECT pg_has_role('procollab_api_dev','procollab_api','MEMBER')"
            )
            self.assertFalse(cursor.fetchone()[0])

    def test_pg14_existing_logins_prepare_owner_then_remove_membership(self):
        import psycopg2

        self.require_postgres14()
        self.seed_runtime_university()
        self.prepare_with_existing_logins()
        self.assert_no_temporary_membership()
        with self.database.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='users_university'::regclass"
            )
            self.assertEqual(cursor.fetchone()[0], MIGRATOR)
        with psycopg2.connect(
            host="127.0.0.1",
            port=self.port,
            dbname="procollab_db_dev",
            user=RUNTIME,
            password=PASSWORD,
        ) as runtime:
            with runtime.cursor() as cursor:
                cursor.execute("SELECT name FROM users_university")
                self.assertEqual(cursor.fetchall(), [("preserve this row",)])
                cursor.execute(
                    "INSERT INTO users_university(name) VALUES('runtime still works') RETURNING id"
                )
                self.assertEqual(cursor.fetchone()[0], 2)
        self.prepare_with_existing_logins()  # Idempotent; no new membership is necessary.
        self.assert_no_temporary_membership()
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pg14_injected_failure_rolls_back_owner_and_revokes_membership(self):
        import psycopg2

        self.require_postgres14()
        self.seed_runtime_university()
        with self.assertRaises(psycopg2.errors.DivisionByZero):
            self.prepare_with_existing_logins(
                "BEGIN; ALTER TABLE users_university OWNER TO procollab_api; SELECT 1/0; COMMIT;"
            )
        self.assert_no_temporary_membership()
        with self.database.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='users_university'::regclass"
            )
            self.assertEqual(cursor.fetchone()[0], RUNTIME)
            cursor.execute("SELECT name FROM users_university")
            self.assertEqual(cursor.fetchall(), [("preserve this row",)])

    def test_pg14_preexisting_membership_is_preserved(self):
        import psycopg2

        self.require_postgres14()
        self.seed_runtime_university()
        runtime = psycopg2.connect(
            host="127.0.0.1",
            port=self.port,
            dbname="procollab_db_dev",
            user=RUNTIME,
            password=PASSWORD,
        )
        runtime.autocommit = True
        try:
            with runtime.cursor() as cursor:
                cursor.execute("GRANT procollab_api_dev TO procollab_api")
            self.prepare_with_existing_logins()
            with self.database.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_has_role('procollab_api','procollab_api_dev','MEMBER')"
                )
                self.assertTrue(cursor.fetchone()[0])
        finally:
            with runtime.cursor() as cursor:
                cursor.execute("REVOKE procollab_api_dev FROM procollab_api")
            runtime.close()

    def test_owner_preparation_rejects_unverified_postgres_major_before_grant(self):
        if self.database.server_version // 10000 == 14:
            self.skipTest("This server supports the verified PostgreSQL 14 procedure")
        self.seed_runtime_university()
        with self.assertRaisesRegex(
            PREPARATION.PreparationError, "verified only on PostgreSQL 14"
        ):
            self.prepare_with_existing_logins()
        self.assert_no_temporary_membership()


if __name__ == "__main__":
    unittest.main()
