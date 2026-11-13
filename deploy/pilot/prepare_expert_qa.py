"""Отдельные синтетические программы и работы для приемки пилота."""

import json
import re
import sys
from datetime import timedelta


def prepare_fixture(*, key, password, local=False):
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction
    from django.utils import timezone

    from partner_programs.models import (
        PartnerProgram,
        PartnerProgramField,
        PartnerProgramFieldValue,
        PartnerProgramProject,
        PartnerProgramUserProfile,
    )
    from partner_programs.services.project_fields import submit_program_project
    from procollab.white_label import get_config
    from project_rates.models import (
        Criteria,
        ExpertCaseScope,
        ProjectExpertAssignment,
        ProjectScore,
    )
    from projects.models import Project
    from users.models import Expert

    brand = get_config()
    db = connection.settings_dict
    allowed = (
        brand.enabled
        and brand.frontend_url == "https://pilot.procollab.ru"
        and db["NAME"] == "procollab_white_label_pilot_v2"
        and db["USER"] == "procollab_pilot_v2"
        and db["HOST"] == "db"
    )
    if local:
        allowed = (
            brand.enabled
            and brand.frontend_url == "http://127.0.0.1:18461"
            and db["NAME"] in ("procollab_white_label_expert_qa", "test_pilot_expert_qa")
            and db["USER"] == "pilot_expert_qa"
            and db["HOST"] == "127.0.0.1"
            and str(db["PORT"]) == "15451"
        )
    if not allowed:
        raise ValueError(
            "Тестовые данные разрешены только в проверенном пилоте или локальной QA БД."
        )
    if not re.fullmatch(r"[a-z0-9-]{8,28}", key) or len(password) < 16:
        raise ValueError("Некорректные параметры отдельного набора приемки.")
    if not PartnerProgram.objects.filter(pk=brand.program_id).exists():
        raise ValueError("Не найдена основная программа white label.")
    tag = "qa-pilot-" + key
    users = get_user_model()
    now = timezone.now()
    with transaction.atomic():
        if PartnerProgram.objects.filter(tag__in=(tag, tag + "-other")).exists():
            raise ValueError(
                "Такой набор приемки уже существует; оценки не перезаписываются."
            )
        before = list(ProjectScore.objects.order_by("pk").values_list("pk", "value"))

        def user(suffix, first_name):
            return users.objects.create_user(
                email=f"{tag}-{suffix}@example.invalid",
                password=password,
                first_name=first_name,
                last_name="Приемка пилота",
                birthday="1990-01-01",
                is_active=True,
                user_type=users.MEMBER,
            )

        manager = user("manager", "Организатор")
        evaluator = user("expert", "Эксперт")
        defaults = dict(
            description="Отдельная приемка кабинета эксперта. Синтетические работы.",
            city="Москва",
            data_schema={},
            draft=False,
            program_format="case_championship",
            solution_storage_mode="legacy_project",
            projects_availability="all_users",
            is_competitive=True,
            is_distributed_evaluation=True,
            required_evaluators=1,
            legacy_team_min_size=1,
            max_project_rates=2,
            datetime_started=now - timedelta(days=1),
            datetime_registration_ends=now + timedelta(days=2),
            datetime_project_submission_ends=now + timedelta(days=2),
            datetime_evaluation_ends=now + timedelta(days=10),
            datetime_finished=now + timedelta(days=11),
        )
        program = PartnerProgram.objects.create(
            name=f"[QA PILOT] Проверка оценивания {key}", tag=tag, **defaults
        )
        other = PartnerProgram.objects.create(
            name=f"[QA PILOT] Другая анкета {key}", tag=tag + "-other", **defaults
        )
        for scope in (program, other):
            scope.managers.add(manager)
        manager.refresh_from_db()
        assert manager.user_type == users.MEMBER and not manager.is_staff
        assert not manager.expert.project_assignments.exists()
        expert, _ = Expert.objects.get_or_create(user=evaluator)
        expert.programs.add(program, other)
        for scope in (program, other):
            ExpertCaseScope.objects.get_or_create(partner_program=scope, expert=expert)

        number = Criteria.objects.create(
            partner_program=program, name="Баллы", type="int", min_value=0, max_value=10
        )
        boolean = Criteria.objects.create(
            partner_program=program, name="Критерий выполнен", type="bool"
        )
        Criteria.objects.get_or_create(
            partner_program=program, name="Комментарий", type="str"
        )
        Criteria.objects.create(
            partner_program=other,
            name="Баллы другой программы",
            type="int",
            min_value=0,
            max_value=10,
        )

        def fields(scope, secondary=False):
            track = PartnerProgramField.objects.create(
                partner_program=scope,
                name="track",
                label="Направление",
                field_type="radio",
                options="Право|Медиа" if secondary else "Город|Образование",
                is_required=True,
                show_filter=True,
            )
            case = PartnerProgramField.objects.create(
                partner_program=scope,
                name="case",
                label="Кейс",
                field_type="select",
                purpose="case",
                options="Правовой кейс" if secondary else "Городской кейс",
                is_required=True,
                show_filter=True,
            )
            answer = PartnerProgramField.objects.create(
                partner_program=scope,
                name="answer",
                label="Ответ команды",
                field_type="text",
                is_required=True,
            )
            return track, case, answer

        main_fields, foreign_fields = fields(program), fields(other, secondary=True)

        def fill(link, defined, track, case, text):
            PartnerProgramFieldValue.objects.bulk_create(
                [
                    PartnerProgramFieldValue(
                        program_project=link, field=field, value_text=value
                    )
                    for field, value in zip(defined, (track, case, text))
                ]
            )

        def work(suffix, name, track, submitted=True):
            leader = user("leader-" + suffix, "Команда")
            project = Project.objects.create(
                leader=leader,
                name=name,
                description="Описание синтетической работы для приемки.",
                draft=submitted,
                is_public=False,
            )
            PartnerProgramUserProfile.objects.create(
                partner_program=program,
                user=leader,
                project=project,
                partner_program_data={},
            )
            link = PartnerProgramProject.objects.create(
                partner_program=program, project=project
            )
            fill(
                link,
                main_fields,
                track,
                "Городской кейс",
                "Ответ из основной тестовой программы",
            )
            if submitted:
                submit_program_project(link.pk, leader)
            # Несданное назначение воспроизводит исторические записи, видимые эксперту.
            ProjectExpertAssignment.objects.create(
                partner_program=program, project=project, expert=expert
            )
            return project, link

        first, first_link = work("first", "Проверка 0 баллов и ответа Нет", "Город")
        partial, _ = work("partial", "Старая частичная оценка", "Образование")
        blocked, _ = work(
            "blocked", "Несданная тестовая работа", "Образование", submitted=False
        )
        ProjectScore.objects.create(
            project=partial, criteria=number, user=evaluator, value="0"
        )
        # Общий проект с разными анкетами воспроизводит старые межпрограммные связи.
        PartnerProgramUserProfile.objects.create(
            partner_program=other,
            user=first.leader,
            project=first,
            partner_program_data={},
        )
        foreign = PartnerProgramProject(
            partner_program=other, project=first, submitted=True, datetime_submitted=now
        )
        PartnerProgramProject.objects.bulk_create([foreign])
        fill(
            foreign,
            foreign_fields,
            "Право",
            "Правовой кейс",
            "Ответ только из другой программы",
        )
        ProjectExpertAssignment.objects.create(
            partner_program=other, project=first, expert=expert
        )
        assert (
            list(
                ProjectScore.objects.filter(pk__in=[row[0] for row in before])
                .order_by("pk")
                .values_list("pk", "value")
            )
            == before
        )
        assert evaluator.user_type == users.MEMBER
    return {
        "key": key,
        "program_id": program.pk,
        "other_program_id": other.pk,
        "project_id": first.pk,
        "program_link_id": first_link.pk,
        "partial_project_id": partial.pk,
        "unsubmitted_project_id": blocked.pk,
        "expert_email": evaluator.email,
        "expert_user_id": evaluator.pk,
        "manager_email": manager.email,
        "manager_user_id": manager.pk,
        "number_criterion_id": number.pk,
        "boolean_criterion_id": boolean.pk,
        "manager_primary_role_preserved": True,
        "manager_auto_assignments": 0,
        "existing_scores_unchanged": True,
    }


if __name__ == "__main__":
    import django

    django.setup()
    configuration = json.load(sys.stdin)
    result = prepare_fixture(**configuration)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
