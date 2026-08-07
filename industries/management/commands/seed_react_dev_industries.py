from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from industries.reference_data import ensure_react_dev_industries


class Command(BaseCommand):
    help = "Заполнить обязательный справочник отраслей в изолированной React-dev базе."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-react-dev",
            action="store_true",
            help="Подтвердить, что команда подключена к изолированной React-dev базе.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать результат и откатить созданные записи.",
        )

    def handle(self, *args, **options):
        # Используем существующий закрытый по умолчанию guard, чтобы команда не могла
        # случайно изменить production или legacy dev при обычной конфигурации.
        if not settings.ALLOW_REACT_DEV_DEMO_SEED:
            raise CommandError(
                "Заполнение справочников React-dev отключено в настройках."
            )
        if not options["confirm_react_dev"]:
            raise CommandError("Для запуска передайте флаг --confirm-react-dev.")

        with transaction.atomic():
            summary = ensure_react_dev_industries()
            if options["dry_run"]:
                transaction.set_rollback(True)

        self.stdout.write(f"Создано отраслей: {summary.created}")
        self.stdout.write(f"Уже существовало: {summary.existing}")
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    "Пробный запуск завершён; созданные записи не сохранены."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("Справочник отраслей готов."))
