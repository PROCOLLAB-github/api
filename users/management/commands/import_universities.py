import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction

from users.models import University


class Command(BaseCommand):
    help = (
        "Импорт справочника вузов из JSON; существующие записи сохраняются по умолчанию."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Обновить названия и сведения об источнике для существующих кодов. Активность сохраняется.",
        )

    def handle(self, *args, **options):
        try:
            document = json.loads(options["path"].read_text(encoding="utf-8"))
            checked_at = date.fromisoformat(document["checked_at"])
            source_url = document["source_url"]
            rows = document["universities"]
            if not isinstance(rows, list) or not rows:
                raise ValueError("Список universities должен быть непустым массивом")
            prepared = []
            codes = set()
            for row in rows:
                code = row["source_id"]
                if not code or code in codes:
                    raise ValueError("Коды source_id должны быть заполнены и уникальны")
                codes.add(code)
                university = University(
                    source_id=code,
                    name=row["name"],
                    full_name=row.get("full_name", row["name"]),
                    aliases=row.get("aliases", ""),
                    city=row.get("city", ""),
                    source_url=row.get("source_url", source_url),
                    source_checked_at=checked_at,
                )
                university.full_clean(validate_unique=False)
                prepared.append(university)
        except (OSError, ValueError, KeyError, TypeError, ValidationError) as error:
            raise CommandError(f"Неверный файл справочника: {error}") from error

        created = updated = 0
        with transaction.atomic():
            for university in prepared:
                existing = University.objects.filter(
                    source_id=university.source_id
                ).first()
                if existing is None:
                    university.save()
                    created += 1
                elif options["update_existing"]:
                    for field in (
                        "name",
                        "full_name",
                        "aliases",
                        "city",
                        "source_url",
                        "source_checked_at",
                    ):
                        setattr(existing, field, getattr(university, field))
                    existing.save()
                    updated += 1
        self.stdout.write(
            self.style.SUCCESS(f"Добавлено: {created}, обновлено: {updated}")
        )
