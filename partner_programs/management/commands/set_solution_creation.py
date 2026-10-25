"""Отдельный rollout/rollback только создания, без переключения storage mode."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from partner_programs.models import PartnerProgram
from partner_programs.solution_errors import MAX_ID


class Command(BaseCommand):
    help = "Предпросмотр или изменение создания решений одной программы."

    def add_arguments(self, parser):
        parser.add_argument("--program-id", type=int, required=True)
        action = parser.add_mutually_exclusive_group(required=True)
        action.add_argument("--enable", action="store_true")
        action.add_argument("--disable", action="store_true")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        program_id = options["program_id"]
        if not 0 < program_id <= MAX_ID:
            raise CommandError("Укажите допустимый ID программы.")
        with transaction.atomic():
            program = (
                PartnerProgram.objects.select_for_update().filter(pk=program_id).first()
            )
            if program is None:
                raise CommandError("Программа не найдена.")
            enabled = options["enable"]
            if enabled and program.solution_storage_mode != "solution":
                raise CommandError("Сначала настройте режим решения выбранной программы.")
            previous = program.solution_creation_enabled
            if options["apply"] and previous != enabled:
                program.solution_creation_enabled = enabled
                program.save(update_fields=["solution_creation_enabled"])
            receipt = dict(
                program_id=program.pk,
                storage_mode=program.solution_storage_mode,
                previous_enabled=previous,
                requested_enabled=enabled,
                applied=options["apply"],
                changed=options["apply"] and previous != enabled,
            )
        self.stdout.write(json.dumps(receipt, ensure_ascii=False))
