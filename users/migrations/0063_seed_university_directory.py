"""Frozen official-source snapshot. No changes to UserEducation or existing directory rows."""

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from django.db import migrations


def seed_universities(apps, schema_editor):
    University = apps.get_model("users", "University")
    database = schema_editor.connection.alias
    snapshot = (
        Path(__file__).resolve().parent.parent / "data" / "universities_20261004.json"
    )
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    for row in document["universities"]:
        text = " ".join((row["name"], row["full_name"], row["aliases"], row["city"]))
        text = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
        University.objects.using(database).get_or_create(
            source_id=row["source_id"],
            defaults={
                "name": row["name"],
                "full_name": row["full_name"],
                "aliases": row["aliases"],
                "city": row["city"],
                "source_url": document["source_url"],
                "source_checked_at": date.fromisoformat(document["checked_at"]),
                "search_text": " ".join(re.findall(r"\w+", text)),
            },
        )


class Migration(migrations.Migration):
    dependencies = [("users", "0062_university_directory")]
    operations = [migrations.RunPython(seed_universities, migrations.RunPython.noop)]
