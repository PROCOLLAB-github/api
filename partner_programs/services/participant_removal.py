"""Удаление регистрации организатором с явным подтверждением заявок лидеров."""

import logging

from django.core import signing
from django.db import transaction
from rest_framework.exceptions import APIException

from partner_programs.models import PartnerProgram, PartnerProgramProject
from partner_programs.services.management import managed_program, participant_rows
from project_rates.models import ProjectExpertAssignment, ProjectScore
from projects.models import Project

logger = logging.getLogger(__name__)
SALT = "management-participant-removal-v1"


class RemovalConflict(APIException):
    status_code = 409

    def __init__(
        self,
        code="selection_changed",
        detail="Состав участников или заявки изменились. Обновите список и повторите удаление.",
    ):
        super().__init__({"code": code, "detail": detail})


def selected_profiles(program, ids, *, lock=False):
    rows = participant_rows(program).filter(pk__in=ids).order_by("pk")
    if lock:
        rows = rows.select_for_update(of=("self",))
    profiles = list(rows)
    if len(profiles) != len(set(ids)):
        raise RemovalConflict()
    return profiles


def applications(program, profiles):
    return list(
        PartnerProgramProject.objects.filter(
            partner_program=program, project__leader_id__in=[p.user_id for p in profiles]
        )
        .select_related("project")
        .order_by("pk")
    )


def snapshot(program, profiles, links):
    projects = [link.project_id for link in links]
    return {
        "profiles": [[p.pk, p.user_id] for p in profiles],
        "applications": [
            [
                link.pk,
                link.project_id,
                link.project.leader_id,
                link.submitted,
                link.datetime_updated.isoformat(),
            ]
            for link in links
        ],
        "assignments": list(
            ProjectExpertAssignment.objects.filter(
                partner_program=program, project_id__in=projects
            )
            .order_by("pk")
            .values_list("pk", "project_id", "expert_id")
        ),
        "scores": list(
            ProjectScore.objects.filter(
                criteria__partner_program=program, project_id__in=projects
            )
            .order_by("pk")
            .values_list("pk", "project_id", "criteria_id", "user_id", "value")
        ),
    }


def normalized_snapshot(program, profiles, links):
    # JSON-signing сохраняет tuples как lists; оба прохода сравнивают одну форму.
    state = snapshot(program, profiles, links)
    state["assignments"] = [list(row) for row in state["assignments"]]
    state["scores"] = [list(row) for row in state["scores"]]
    return state


def preview_removal(program_id, actor, ids):
    program = managed_program(program_id, actor)
    profiles = selected_profiles(program, ids)
    links = applications(program, profiles)
    state = normalized_snapshot(program, profiles, links)
    token = signing.dumps(
        {
            "program": program.pk,
            "actor": actor.pk,
            "ids": sorted(set(ids)),
            "state": state,
        },
        salt=SALT,
        compress=True,
    )
    return {
        "preview_token": token,
        "participant_count": len(profiles),
        "applications": [
            {
                "id": link.pk,
                "project_id": link.project_id,
                "name": link.project.name,
                "submitted": link.submitted,
            }
            for link in links
        ],
        "assignments_count": len(state["assignments"]),
    }


@transaction.atomic
def remove_participants(program_id, actor, ids, token):
    program = managed_program(program_id, actor)
    try:
        proof = signing.loads(token, salt=SALT, max_age=900)
    except signing.BadSignature:
        raise RemovalConflict(
            "preview_expired", "Подтверждение устарело. Откройте удаление еще раз."
        )
    ids = sorted(set(ids))
    if (
        proof.get("program") != program.pk
        or proof.get("actor") != actor.pk
        or proof.get("ids") != ids
    ):
        raise RemovalConflict()
    profiles = selected_profiles(program, ids)
    user_ids = [p.user_id for p in profiles]
    project_ids = set(
        PartnerProgramProject.objects.filter(
            partner_program=program, project__leader_id__in=user_ids
        ).values_list("project_id", flat=True)
    )
    # Тот же порядок, что у lock_team: сначала Project, затем программы и профили.
    # Все проекты блокируются до программ, чтобы массовая операция не меняла порядок.
    # FK-проверка новой оценки берет KEY SHARE проекта при commit. Разрешаем ее,
    # пока ожидаем программу: оценка завершится, а измененный preview даст 409.
    list(
        Project.objects.select_for_update(no_key=True)
        .filter(pk__in=project_ids)
        .order_by("pk")
    )
    program_ids = set(
        PartnerProgramProject.objects.filter(project_id__in=project_ids).values_list(
            "partner_program_id", flat=True
        )
    ) | {program.pk}
    list(
        PartnerProgram.objects.select_for_update()
        .filter(pk__in=program_ids)
        .order_by("pk")
    )
    program = managed_program(program_id, actor)
    profiles = selected_profiles(program, ids, lock=True)
    links = applications(program, profiles)
    if {link.project_id for link in links} != project_ids or normalized_snapshot(
        program, profiles, links
    ) != proof.get("state"):
        raise RemovalConflict()
    link_ids = [link.pk for link in links]
    ProjectExpertAssignment.objects.filter(
        partner_program=program, project_id__in=project_ids
    ).delete()
    # Отдельная команда организатора с подписанным preview. Обычный model.delete
    # по-прежнему запрещает участнику удалять сданную заявку. Здесь удаляется
    # только program link и его поля; Project, Collaborator и ProjectScore целы.
    PartnerProgramProject.objects.filter(
        partner_program=program, pk__in=link_ids
    ).delete()
    for profile in profiles:
        profile.delete()
    logger.info(
        "Program registration removal program=%s actor=%s profiles=%s applications=%s",
        program.pk,
        actor.pk,
        ids,
        link_ids,
    )
    return {"removed": len(profiles), "removed_applications": len(link_ids)}
