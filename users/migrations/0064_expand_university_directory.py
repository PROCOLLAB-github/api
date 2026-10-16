"""Expand the frozen directory, preserving administrator edits and education strings."""

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from django.db import migrations, models


def row_defaults(row, document):
    fields = {
        "name": row["name"],
        "full_name": row["full_name"],
        "aliases": row["aliases"],
        "city": row["city"],
        "source_url": row.get("source_url", document["source_url"]),
        "source_checked_at": date.fromisoformat(document["checked_at"]),
    }
    text = " ".join(fields[key] for key in ("name", "full_name", "aliases", "city"))
    text = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    fields["search_text"] = " ".join(re.findall(r"\w+", text))
    return fields


def expand_universities(apps, schema_editor):
    University = apps.get_model("users", "University")
    database = schema_editor.connection.alias
    data = Path(__file__).resolve().parent.parent / "data"
    original = json.loads((data / "universities_20261004.json").read_text(encoding="utf-8"))
    expanded = json.loads((data / "universities_20261004_full.json").read_text(encoding="utf-8"))
    original_defaults = {
        row["source_id"]: row_defaults(row, original) for row in original["universities"]
    }
    existing = {
        university.source_id: university
        for university in University.objects.using(database).all()
        if university.source_id
    }

    def unchanged_seed(university):
        defaults = original_defaults.get(university.source_id)
        return university.is_active and defaults is not None and all(
            getattr(university, field) == value for field, value in defaults.items()
        )

    missing = []
    for row in expanded["universities"]:
        defaults = row_defaults(row, expanded)
        university = existing.get(row["source_id"])
        if university is None:
            missing.append(University(source_id=row["source_id"], **defaults))
        elif unchanged_seed(university):
            for field, value in defaults.items():
                setattr(university, field, value)
            university.save(using=database, update_fields=[*defaults, "updated_at"])
    University.objects.using(database).bulk_create(missing)

    # Hide the unedited old suggestion after a merger. The former name remains
    # searchable on the successor, and no saved UserEducation value is changed.
    for row in expanded["retired_legacy"]:
        university = existing.get(row["source_id"])
        if university is not None and unchanged_seed(university):
            university.is_active = False
            university.save(using=database, update_fields=["is_active", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("users", "0063_seed_university_directory")]
    operations = [
        migrations.AlterField(
            model_name="university",
            name="source_url",
            field=models.URLField(blank=True, max_length=1000, verbose_name="Источник"),
        ),
        migrations.RunPython(expand_universities, migrations.RunPython.noop),
    ]
