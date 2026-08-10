# Roadmap: DEV-072, DEV-083
# Безопасная точка запуска демонстрационного набора только для React-dev.

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from partner_programs.services.react_dev_demo import (
    DEMO_PROGRAM_NAME,
    DEMO_USER_SPECS,
    ReactDevDemoDataError,
    build_react_dev_demo_data,
)


class Command(BaseCommand):
    help = "Создать или обновить DEMO-набор экспертной оценки для React-dev."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-react-dev",
            action="store_true",
            help="Подтвердить, что используется изолированная база данных React-dev.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Удалить точную DEMO-программу и заново создать ее набор данных.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Построить набор в транзакции и откатить все изменения.",
        )

    def handle(self, *args, **options):
        if not settings.ALLOW_REACT_DEV_DEMO_SEED:
            raise CommandError("Создание DEMO-данных React-dev отключено в настройках.")
        if not options["confirm_react_dev"]:
            raise CommandError("Для запуска передайте флаг --confirm-react-dev.")

        password = os.environ.get("REACT_DEV_DEMO_PASSWORD")
        if not password:
            raise CommandError("Требуется переменная окружения REACT_DEV_DEMO_PASSWORD.")

        mode = "пересоздание" if options["reset"] else "создание/обновление"
        if options["dry_run"]:
            mode = f"пробный запуск: {mode}"
        self.stdout.write(f"План: {mode}")
        self.stdout.write(f"Программа: {DEMO_PROGRAM_NAME}")
        self.stdout.write(
            "Пользователи: " + ", ".join(spec["email"] for spec in DEMO_USER_SPECS)
        )

        try:
            summary = build_react_dev_demo_data(
                password=password,
                reset=options["reset"],
                dry_run=options["dry_run"],
            )
        except ReactDevDemoDataError as exc:
            raise CommandError(str(exc)) from exc

        labels = {
            "users": "пользователи",
            "programs": "программы",
            "program_memberships": "участники программ",
            "applications": "заявки",
            "teams": "команды",
            "team_members": "участники команд",
            "criteria": "критерии",
            "submissions": "сдачи",
            "assignments": "назначения",
            "evaluations": "оценки",
            "scores": "баллы",
            "projects": "проекты",
            "public_news": "публичные новости",
            "internal_news": "внутренние новости",
            "likes": "лайки",
            "views": "просмотры",
            "comments": "комментарии",
            "internal_news_id": "ID внутренней новости",
        }
        self.stdout.write("Результат:")
        for label, count in summary.as_dict().items():
            self.stdout.write(f"  {labels[label]}: {count}")
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("Пробный запуск завершен; все изменения отменены.")
            )
        else:
            self.stdout.write(self.style.SUCCESS("DEMO-данные React-dev готовы."))
