from django.core.management.base import BaseCommand, CommandError

from partner_programs.services.white_label_experts import (
    ensure_organizer_experts,
    organizer_expert_program_id,
)


class Command(BaseCommand):
    help = "Добавить организаторов изолированного пилота в эксперты своей программы."

    def handle(self, *args, **options):
        program_id = organizer_expert_program_id()
        if program_id is None:
            raise CommandError("Автоматическое экспертное членство пилота выключено.")
        added = ensure_organizer_experts(program_id)
        self.stdout.write(
            f"Программа {program_id}: добавлено экспертных членств — {added}."
        )
