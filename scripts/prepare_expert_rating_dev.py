"""Prepare an isolated project to verify expert scoring on DEV."""

import os
import re
import sys
from datetime import timedelta


def main():
    sys.path.insert(0, os.getcwd())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.utils import timezone
    from partner_programs.models import (
        PartnerProgram,
        PartnerProgramField,
        PartnerProgramFieldValue,
        PartnerProgramProject,
        PartnerProgramUserProfile,
    )
    from partner_programs.services.project_fields import submit_program_project
    from project_rates.models import Criteria, ProjectExpertAssignment
    from projects.models import Project
    from users.models import Expert

    if (
        settings.EXPERT_WORKSPACE_FRONTEND_URL != "https://dev.procollab.ru"
        or settings.PROGRAM_SOLUTIONS_ENABLED
        or os.environ["VERIFY_PHASE"] != "prepare_expert_rating"
        or os.environ["VERIFY_FIXTURE_APPLY"] != "true"
    ):
        raise ValueError("This fixture requires the DEV project environment.")
    key = os.environ["VERIFY_FIXTURE_KEY"]
    if not re.fullmatch(r"[a-z0-9-]{8,28}", key):
        raise ValueError("Invalid expert rating fixture key.")
    expert = Expert.objects.get(
        user_id=int(os.environ["VERIFY_MANAGER_ID"]), user__is_active=True
    )
    tag = "qa-expert-" + key
    with transaction.atomic():
        if PartnerProgram.objects.filter(tag=tag).exists():
            raise ValueError("Fixture already exists.")
        leader = get_user_model().objects.create_user(
            email=f"{tag}@example.invalid",
            first_name="Приемка",
            last_name="Оценивание",
            birthday="1990-01-01",
            is_active=True,
        )
        now = timezone.now()
        program = PartnerProgram.objects.create(
            name=f"[QA DEV] Оценка проекта {key}",
            tag=tag,
            description="Изолированная проверка пути эксперта.",
            city="Москва",
            draft=False,
            program_format="case_championship",
            solution_storage_mode="legacy_project",
            is_competitive=True,
            is_distributed_evaluation=True,
            required_evaluators=1,
            legacy_team_min_size=1,
            datetime_started=now - timedelta(days=1),
            datetime_registration_ends=now - timedelta(hours=1),
            datetime_project_submission_ends=now + timedelta(days=1),
            datetime_evaluation_ends=now + timedelta(days=2),
            datetime_finished=now + timedelta(days=3),
        )
        expert.programs.add(program)
        project = Project.objects.create(
            leader=leader,
            name="Проверка оценки DEV",
            description="Описание тестового проекта.",
            draft=True,
            is_public=False,
        )
        PartnerProgramUserProfile.objects.create(
            partner_program=program, user=leader, project=project, partner_program_data={}
        )
        link = PartnerProgramProject.objects.create(
            partner_program=program, project=project
        )
        field = PartnerProgramField.objects.create(
            partner_program=program,
            name="track",
            label="Направление",
            field_type="radio",
            options="Город|Образование",
            is_required=True,
            show_filter=True,
        )
        PartnerProgramFieldValue.objects.create(
            program_project=link, field=field, value_text="Город"
        )
        case = PartnerProgramField.objects.create(
            partner_program=program,
            name="case",
            label="Кейс",
            field_type="select",
            purpose="case",
            options="Город",
            is_required=True,
            show_filter=True,
        )
        PartnerProgramFieldValue.objects.create(
            program_project=link, field=case, value_text="Город"
        )
        Criteria.objects.create(
            partner_program=program, name="Баллы", type="int", min_value=0, max_value=10
        )
        Criteria.objects.create(
            partner_program=program, name="Критерий выполнен", type="bool"
        )
        submit_program_project(link.pk, leader)
        ProjectExpertAssignment.objects.create(
            partner_program=program, project=project, expert=expert
        )
    sys.stdout.write(f"DEV_EXPERT_RATING_PROGRAM={program.pk} PROJECT={project.pk}\n")


if __name__ == "__main__":
    main()
