"""Повторяемое наполнение только явно разрешенной локальной демо-БД."""

import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError, no_translations
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils import timezone

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
    ProgramRegistration,
)
from partner_programs.services.native_registration import create_enrollment, save_settings
from procollab.white_label import get_config
from projects.models import Collaborator, Project
from users.models import CustomUser


class Command(BaseCommand):
    help = "Создать вымышленный КЧ и роли в отдельной локальной white label БД."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="WhiteLabel-demo-2026!")

    @no_translations
    @transaction.atomic
    def handle(self, *args, **options):
        database = connection.settings_dict
        if not (
            getattr(settings, "WHITE_LABEL_DEMO_ALLOWED", False)
            and connection.vendor == "postgresql"
            and database["HOST"] in ("127.0.0.1", "localhost", "::1")
            and database["NAME"].startswith(
                ("procollab_white_label", "test_procollab_white_label")
            )
        ):
            raise CommandError(
                "Демо разрешено только с WHITE_LABEL_DEMO_ALLOWED=True "
                "на отдельной локальной PostgreSQL БД procollab_white_label*."
            )
        config = get_config()
        if not config.enabled:
            raise CommandError("Включите и настройте WHITE_LABEL_ENABLED.")
        if CustomUser.objects.exclude(email__endswith="@example.test").exists():
            raise CommandError(
                "БД содержит учетные записи вне вымышленного example.test."
            )
        if PartnerProgram.objects.exclude(tag="white-label-demo").exists():
            raise CommandError("БД содержит программы вне этого демо.")

        now = timezone.now()
        roles = {}
        for role, name in (
            ("admin", "Администратор"),
            ("organizer", "Организатор"),
            ("expert", "Эксперт"),
            ("leader", "Лидер"),
            ("member", "Участник"),
        ):
            user, created = CustomUser.objects.get_or_create(
                email=f"{role}@example.test",
                defaults={
                    "first_name": name,
                    "last_name": "Демонстрационный",
                    "birthday": "2000-01-01",
                    "is_active": True,
                    "is_staff": role in ("admin", "organizer"),
                    "is_superuser": role == "admin",
                    "onboarding_stage": None,
                    "user_type": CustomUser.EXPERT
                    if role == "expert"
                    else CustomUser.MEMBER,
                },
            )
            if created:
                user.set_password(options["password"])
                user.save(update_fields=["password"])
            roles[role] = user

        program, created = PartnerProgram.objects.get_or_create(
            pk=config.program_id,
            defaults={
                "name": "Демонстрационный кейс-чемпионат",
                "tag": "white-label-demo",
                "city": "Тестовая среда",
                "description": "Вымышленные данные для проверки отдельного экземпляра.",
                "draft": False,
                "is_competitive": True,
                "program_format": "case_championship",
                "datetime_started": now,
                "datetime_finished": now + timedelta(days=30),
                "datetime_registration_ends": now + timedelta(days=30),
            },
        )
        if program.tag != "white-label-demo":
            raise CommandError("ID настроенной программы занят другими данными.")
        if created:
            with connection.cursor() as cursor:
                for statement in connection.ops.sequence_reset_sql(
                    no_style(), [PartnerProgram]
                ):
                    cursor.execute(statement)
        program.managers.add(roles["organizer"])
        roles["expert"].expert.programs.add(program)
        roles["organizer"].user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label__in=("partner_programs", "project_rates"),
            )
        )

        schema = {"mode": "native", "fields": []}
        if not ProgramRegistration.objects.filter(program=program).exists():
            save_settings(
                program.pk,
                roles["organizer"],
                {"revision": 0, "draft": schema},
                publish=True,
            )
        for role in ("leader", "member"):
            create_enrollment(program, roles[role], {}, schema)
        leader = roles["leader"]
        project, _ = Project.objects.get_or_create(
            leader=leader,
            name="Демонстрационная команда",
            defaults={"description": "Вымышленная команда", "draft": False},
        )
        for role in ("leader", "member"):
            Collaborator.objects.get_or_create(project=project, user=roles[role])
        link, _ = PartnerProgramProject.objects.get_or_create(
            partner_program=program, project=project
        )
        PartnerProgramUserProfile.objects.filter(
            partner_program=program, user__in=[roles["leader"], roles["member"]]
        ).update(project=project)

        self.stdout.write(
            json.dumps(
                {
                    "program_id": program.pk,
                    "project_id": project.pk,
                    "program_project_id": link.pk,
                    "accounts": {role: user.email for role, user in roles.items()},
                    "registration_url": (
                        f"{config.frontend_url}/program-registration/{program.pk}"
                    ),
                },
                ensure_ascii=False,
            )
        )
