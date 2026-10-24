"""Удаление регистрации и членства в командах заявок с подписанным preview."""

import logging
from collections import Counter

from django.core import signing
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import APIException

from invites.models import Invite
from partner_programs.models import PartnerProgram, PartnerProgramProject
from partner_programs.services.management import (
    managed_program,
    participant_rows,
    person_name,
)
from project_rates.models import ProjectExpertAssignment, ProjectScore
from projects.models import Collaborator, Project

logger = logging.getLogger(__name__)
SALT = "management-participant-removal-v2"


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


def require_legacy_removal(program):
    if program.solution_storage_mode == "solution":
        raise RemovalConflict(
            "solution_mode_unavailable",
            "Нельзя удалять регистрации отдельно от заявки решения.",
        )


def applications(program, profiles):
    return list(
        PartnerProgramProject.objects.filter(
            partner_program=program, project__leader_id__in=[p.user_id for p in profiles]
        )
        .select_related("project")
        .order_by("pk")
    )


def application_effects(program, profiles):
    links = applications(program, profiles)
    user_ids = [p.user_id for p in profiles]
    member_projects = Collaborator.objects.filter(user_id__in=user_ids).values(
        "project_id"
    )
    invitation_projects = (
        Invite.objects.filter(user_id__in=user_ids)
        .filter(Q(program_link__partner_program=program) | Q(program_link__isnull=True))
        .values("project_id")
    )
    team_links = list(
        PartnerProgramProject.objects.filter(partner_program=program)
        .filter(Q(project_id__in=member_projects) | Q(project_id__in=invitation_projects))
        .exclude(project_id__in=[link.project_id for link in links])
        .select_related("project")
        .order_by("pk")
    )
    if (
        PartnerProgramProject.objects.filter(
            project_id__in=[link.project_id for link in team_links]
        )
        .exclude(partner_program=program)
        .exists()
    ):
        raise RemovalConflict(
            "shared_application_team",
            "Команда одной из заявок общая для нескольких программ. "
            "Удаление отменено, чтобы не изменить другую программу.",
        )
    return links, team_links


def affected_project_ids(links, team_links):
    return {link.project_id for link in [*links, *team_links]}


def snapshot(program, profiles, links, team_links):
    projects = affected_project_ids(links, team_links)
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
        "team_applications": [
            [
                link.pk,
                link.project_id,
                link.project.leader_id,
                link.submitted,
                link.datetime_updated.isoformat(),
            ]
            for link in team_links
        ],
        "project_links": list(
            PartnerProgramProject.objects.filter(project_id__in=projects)
            .order_by("pk")
            .values_list("pk", "project_id", "partner_program_id")
        ),
        "members": list(
            Collaborator.objects.filter(project_id__in=projects)
            .order_by("pk")
            .values_list("pk", "project_id", "user_id")
        ),
        "invites": [
            [
                row.pk,
                row.project_id,
                row.user_id,
                row.program_link_id,
                row.is_accepted,
                row.datetime_updated.isoformat(),
            ]
            for row in Invite.objects.filter(project_id__in=projects).order_by("pk")
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


def normalized_snapshot(program, profiles, links, team_links):
    # JSON-signing сохраняет tuples как lists; оба прохода сравнивают одну форму.
    state = snapshot(program, profiles, links, team_links)
    for key in ("assignments", "scores", "project_links", "members"):
        state[key] = [list(row) for row in state[key]]
    return state


def preview_removal(program_id, actor, ids):
    program = managed_program(program_id, actor)
    require_legacy_removal(program)
    profiles = selected_profiles(program, ids)
    links, team_links = application_effects(program, profiles)
    state = normalized_snapshot(program, profiles, links, team_links)
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
    user_ids = {p.user_id for p in profiles}
    team_project_ids = {link.project_id for link in team_links}
    team_members = {project_id: [] for project_id in team_project_ids}
    for member in (
        Collaborator.objects.filter(project_id__in=team_project_ids, user_id__in=user_ids)
        .select_related("user")
        .order_by("pk")
    ):
        team_members[member.project_id].append(
            {"id": member.user_id, "name": person_name(member.user)}
        )
    invitation_counts = Counter(
        row[1]
        for row in state["invites"]
        if row[1] in team_project_ids and row[2] in user_ids
    )
    return {
        "confirmation_version": 2,
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
        "assignments_count": ProjectExpertAssignment.objects.filter(
            partner_program=program, project_id__in=[link.project_id for link in links]
        ).count(),
        "team_changes": [
            {
                "id": link.pk,
                "project_id": link.project_id,
                "name": link.project.name,
                "submitted": link.submitted,
                "members": team_members[link.project_id],
                "invitations_count": invitation_counts[link.project_id],
            }
            for link in team_links
        ],
    }


@transaction.atomic
def remove_participants(program_id, actor, ids, token):
    program = managed_program(program_id, actor)
    require_legacy_removal(program)
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
    links, team_links = application_effects(program, profiles)
    project_ids = affected_project_ids(links, team_links)
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
    require_legacy_removal(program)
    profiles = selected_profiles(program, ids, lock=True)
    links, team_links = application_effects(program, profiles)
    if affected_project_ids(links, team_links) != project_ids or normalized_snapshot(
        program, profiles, links, team_links
    ) != proof.get("state"):
        raise RemovalConflict()
    link_ids = [link.pk for link in links]
    team_project_ids = [link.project_id for link in team_links]
    removed_members, _ = Collaborator.objects.filter(
        project_id__in=team_project_ids, user_id__in=user_ids
    ).delete()
    # Обработанные Invite тоже дают READ в приватный проект. Их нельзя оставлять
    # после исключения или дать повторно принять старое pending-приглашение.
    Invite.objects.filter(
        Q(project_id__in=team_project_ids, user_id__in=user_ids)
        | Q(program_link_id__in=link_ids)
    ).delete()
    ProjectExpertAssignment.objects.filter(
        partner_program=program, project_id__in=[link.project_id for link in links]
    ).delete()
    # Отдельная команда организатора с подписанным preview. Обычный model.delete
    # по-прежнему запрещает участнику удалять сданную заявку. Здесь удаляется
    # program link и его поля; сами Project и ProjectScore сохраняются.
    PartnerProgramProject.objects.filter(
        partner_program=program, pk__in=link_ids
    ).delete()
    for profile in profiles:
        profile.delete()
    logger.info(
        "Program registration removal program=%s actor=%s profiles=%s applications=%s team_projects=%s",
        program.pk,
        actor.pk,
        ids,
        link_ids,
        team_project_ids,
    )
    return {
        "removed": len(profiles),
        "removed_applications": len(link_ids),
        "removed_team_members": removed_members,
    }
