"""Операции над legacy-командой: авторизация и изменения в одной транзакции."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException

from projects.models import Collaborator, Project
from invites.models import Invite
from partner_programs.models import PartnerProgramUserProfile


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


def _require_pending(invite):
    if invite.is_accepted is not None:
        raise TeamError("invite_already_processed", "Приглашение уже обработано.")


def _require_recipient(invite, actor):
    if not actor or not actor.is_authenticated or invite.user_id != actor.pk:
        raise TeamError(
            "not_invite_recipient",
            "Принять или отклонить приглашение может только его получатель.",
            status_code=403,
        )


def _require_invite_eligible(project, user_id):
    if project.leader_id == user_id:
        raise TeamError(
            "already_project_leader", "Пользователь уже является лидером проекта."
        )
    if Collaborator.objects.filter(project=project, user_id=user_id).exists():
        raise TeamError("already_project_member", "Пользователь уже состоит в проекте.")
    # Сохраняем legacy-контекст до отдельного PR с явной связью программы.
    link = project.program_links.order_by("pk").first()
    if link:
        membership = (
            PartnerProgramUserProfile.objects.select_for_update()
            .filter(partner_program_id=link.partner_program_id, user_id=user_id)
            .first()
        )
        if membership is None:
            raise TeamError(
                "not_program_member", "Пользователь не является участником программы."
            )


def _lock_invite(invite_id):
    reference = get_object_or_404(Invite.objects.only("project_id"), pk=invite_id)
    project = _locked_project(reference.project_id)
    # Повторное чтение после Project lock: revoke мог уже удалить запись.
    invite = get_object_or_404(Invite.objects.select_for_update(), pk=invite_id)
    return project, invite


def _pending_invites(project, user_id):
    return Invite.objects.filter(
        project=project, user_id=user_id, is_accepted__isnull=True
    )


@transaction.atomic
def create_invite(*, project_id, user_id, actor, **fields):
    project = _locked_project(project_id)
    require_team_manager(project, actor)
    _require_invite_eligible(project, user_id)
    pending = _pending_invites(project, user_id)
    if pending.exists():
        raise TeamError(
            "duplicate_pending_invite", "У пользователя уже есть активное приглашение."
        )
    try:
        # Savepoint нужен, чтобы после IntegrityError внешняя транзакция оставалась рабочей.
        with transaction.atomic():
            return Invite.objects.create(project=project, user_id=user_id, **fields)
    except IntegrityError as error:
        if pending.exists():
            raise TeamError(
                "duplicate_pending_invite",
                "У пользователя уже есть активное приглашение.",
            ) from error
        raise


@transaction.atomic
def edit_pending_invite(*, invite_id, actor, **fields):
    project, invite = _lock_invite(invite_id)
    require_team_manager(project, actor)
    _require_pending(invite)
    allowed_fields = {"role", "specialization", "motivational_letter"}
    if fields.keys() - allowed_fields:
        raise TeamError(
            "invalid_invite_fields", "Недопустимые поля приглашения.", status_code=422
        )
    for field, value in fields.items():
        setattr(invite, field, value)
    if fields:
        invite.save(update_fields=[*fields, "datetime_updated"])
    return invite


@transaction.atomic
def accept_invite(*, invite_id, actor):
    project, invite = _lock_invite(invite_id)
    _require_recipient(invite, actor)
    _require_pending(invite)
    _require_invite_eligible(project, invite.user_id)
    try:
        with transaction.atomic():
            Collaborator.objects.create(
                project=project,
                user_id=invite.user_id,
                role=invite.role,
                specialization=invite.specialization,
            )
    except DjangoValidationError as error:
        raise TeamError("invalid_team_member", " ".join(error.messages)) from error
    except IntegrityError as error:
        if Collaborator.objects.filter(project=project, user_id=invite.user_id).exists():
            raise TeamError(
                "already_project_member", "Пользователь уже состоит в проекте."
            ) from error
        raise
    invite.is_accepted = True
    invite.save(update_fields=["is_accepted", "datetime_updated"])
    return invite


@transaction.atomic
def decline_invite(*, invite_id, actor):
    _project, invite = _lock_invite(invite_id)
    _require_recipient(invite, actor)
    _require_pending(invite)
    invite.is_accepted = False
    invite.save(update_fields=["is_accepted", "datetime_updated"])
    return invite


@transaction.atomic
def revoke_invite(*, invite_id, actor):
    project, invite = _lock_invite(invite_id)
    require_team_manager(project, actor)
    _require_pending(invite)
    # Сохраняем DELETE-контракт legacy без переноса unrelated PROD lifecycle полей.
    invite.delete()
