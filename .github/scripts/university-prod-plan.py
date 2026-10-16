"""Validate the candidate graph against production within a read-only transaction."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
import django

django.setup()
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
    executor = MigrationExecutor(connection)
    executor.loader.check_consistent_history(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    expected = [
        ("users", "0063_university_directory", False),
        ("users", "0064_seed_university_directory", False),
        ("users", "0065_expand_university_directory", False),
    ]
    actual = [(migration.app_label, migration.name, backwards) for migration, backwards in plan]
    assert actual == expected, actual
    for migration, backwards in plan:
        print("PROD_PLANNED_MIGRATION=" + migration.app_label + "." + migration.name)
        assert all(
            getattr(operation, "model_name", "university") != "usereducation"
            for operation in migration.operations
        )
    print("PROD_ONLY_DIRECTORY_MIGRATIONS_PENDING=true")
    print("PROD_EDUCATION_SCHEMA_UNCHANGED=true")
