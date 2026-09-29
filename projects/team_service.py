"""Операции над legacy-командой: авторизация и изменения в одной транзакции."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException

from projects.models import Collaborator, Project


class TeamError(APIException):
    status_code = 409

    def __init__(self, code, detail, *, status_code=409):
        self.status_code = status_code
        super().__init__({"code": code, "detail": detail}, code=code)


def require_team_manager(project, actor):
    if not actor or not actor.is_authenticated or project.leader_id != actor.pk:
        raise TeamError(
            "not_project_team_manager",
            "Управлять командой может только лидер проекта.",
            status_code=403,
        )


def _locked_project(project_id):
    return get_object_or_404(Project.objects.select_for_update(), pk=project_id)


def _locked_member(project, user_id):
    member = (
        Collaborator.objects.select_for_update()
        .filter(project=project, user_id=user_id)
        .first()
    )
    if member is None:
        raise TeamError(
            "collaborator_not_found",
            "Пользователь не является участником проекта.",
            status_code=422,
        )
    return member


def _require_not_leader(project, user_id):
    if project.leader_id == user_id:
        raise TeamError(
            "leader_cannot_leave",
            "Перед выходом из проекта передайте права лидера другому участнику.",
            status_code=422,
        )


@transaction.atomic
def remove_member(*, project_id, user_id, actor):
    project = _locked_project(project_id)
    require_team_manager(project, actor)
    _require_not_leader(project, user_id)
    _locked_member(project, user_id).delete()


@transaction.atomic
def leave_team(*, project_id, actor):
    project = _locked_project(project_id)
    _require_not_leader(project, actor.pk)
    _locked_member(project, actor.pk).delete()


@transaction.atomic
def switch_leader(*, project_id, user_id, actor):
    project = _locked_project(project_id)
    require_team_manager(project, actor)
    if project.leader_id == user_id:
        raise TeamError(
            "already_project_leader",
            "Пользователь уже является лидером проекта.",
            status_code=422,
        )
    member = _locked_member(project, user_id)
    project.leader_id = member.user_id
    project.save(update_fields=["leader", "datetime_updated"])


@transaction.atomic
def reject_direct_add(*, project_id, actor):
    project = _locked_project(project_id)
    require_team_manager(project, actor)
    raise TeamError(
        "direct_member_add_unsupported",
        "Для добавления участника отправьте приглашение в проект.",
        status_code=405,
    )
