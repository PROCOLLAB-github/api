"""DEV-only read-only education backup/verification; never log profile contents."""

import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")

import django

django.setup()

from django.contrib import admin
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import resolve
from rest_framework.test import APIRequestFactory

from users.models import UserEducation

phase = sys.argv[1]
assert phase in ("snapshot", "verify")
assert connection.vendor == "postgresql"
with connection.cursor() as cursor:
    cursor.execute("SET default_transaction_read_only = on")
    cursor.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
    assert cursor.fetchone()[0], "DEV migration role cannot create the directory table"

executor = MigrationExecutor(connection)
executor.loader.check_consistent_history(connection)
assert not executor.migration_plan(executor.loader.graph.leaf_nodes())

columns = [field.column for field in UserEducation._meta.local_fields]
quote = connection.ops.quote_name
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT "
        + ", ".join(quote(column) for column in columns)
        + " FROM "
        + quote(UserEducation._meta.db_table)
        + " ORDER BY "
        + quote(UserEducation._meta.pk.column)
    )
    rows = cursor.fetchall()


def canonical(payload):
    return json.dumps(
        payload, ensure_ascii=False, default=str, separators=(",", ":")
    ).encode("utf-8")


payload = json.loads(canonical({"columns": columns, "rows": rows}))
if phase == "snapshot":
    # Stdout is redirected to a private file on the same DEV host, not to CI logs.
    sys.stdout.write(canonical(payload).decode("utf-8"))
    sys.stdout.write("\n")
    sys.exit(0)

baseline = json.loads(Path("/university_rollout/education-before.json").read_text())
assert baseline["columns"] == payload["columns"], "Education schema changed"
index = columns.index(UserEducation._meta.pk.column)
current = {row[index]: row for row in payload["rows"]}
missing = sum(row[index] not in current for row in baseline["rows"])
changed = sum(
    row[index] in current and current[row[index]] != row for row in baseline["rows"]
)
print(f"EDUCATION_BEFORE_COUNT={len(baseline['rows'])}")
print(f"EDUCATION_AFTER_COUNT={len(payload['rows'])}")
print(f"EDUCATION_MISSING_COUNT={missing}")
print(f"EDUCATION_CHANGED_COUNT={changed}")
assert missing == 0 and changed == 0, "Existing education records differ"
preserved = {"columns": columns, "rows": [current[row[index]] for row in baseline["rows"]]}
before_digest = hashlib.sha256(canonical(baseline)).hexdigest()
after_digest = hashlib.sha256(canonical(preserved)).hexdigest()
assert before_digest == after_digest
print(f"EDUCATION_BEFORE_SHA256={before_digest}")
print(f"EDUCATION_PRESERVED_SHA256={after_digest}")
print("EDUCATION_ALL_EXISTING_FIELDS_PRESERVED=true")

from users.models import University

assert University in admin.site._registry
assert University.objects.filter(is_active=True).count() >= 1337
assert ("users", "0064_expand_university_directory") in executor.loader.applied_migrations
factory = APIRequestFactory()
path = "/auth/universities/"
for params in ({}, {"search": "московский политех"}, {"search": "___no_university_20261016___"}):
    request = factory.get(path, params, secure=True, HTTP_HOST="dev.procollab.ru")
    response = resolve(path).func(request)
    assert response.status_code == 200
    if not params:
        assert response.data["count"] >= 1337
        assert response.data["next"]
        assert len(response.data["results"]) == 30
        print("UNIVERSITY_ACTIVE_COUNT=" + str(response.data["count"]))
    elif "no_university" in params["search"]:
        assert response.data["count"] == 0
    else:
        assert response.data["count"] > 0
        assert any("политех" in row["name"].casefold() for row in response.data["results"])
print("UNIVERSITY_SEARCH_AND_PAGINATION_OK=true")
print("UNIVERSITY_DJANGO_ADMIN_REGISTERED=true")
print("DEV_PENDING_MIGRATIONS=0")
