"""Операции над legacy-командой: авторизация и изменения в одной транзакции."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404

from projects.models import Collaborator
from partner_programs.models import (
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from django.utils import timezone
from invites.models import Invite
from projects import team_policy
from projects.team_errors import TeamError


def require_team_manager(project, actor):
    if not actor or not actor.is_authenticated or project.leader_id != actor.pk:
        raise TeamError(
            "not_project_team_manager",
            "Управлять командой может только лидер проекта.",
            status_code=403,
        )


def _locked_project(project_id):
    return team_policy.lock_team(project_id).project


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
    member.project = project
    return member


def _require_not_leader(project, user_id):
    if project.leader_id == user_id:
        raise TeamError(
            "leader_cannot_leave",
            "Перед выходом из проекта передайте права лидера другому участнику.",
            status_code=422,
        )


@transaction.atomic
def remove_member(*, project_id, user_id, actor, program_link_id=None):
    project = _locked_project(project_id)
    require_team_manager(project, actor)
    team_policy.resolve_program_context(project, program_link_id)
    team_policy.require_mutable_team(project)
    _require_not_leader(project, user_id)
    _locked_member(project, user_id).delete()


@transaction.atomic
def leave_team(*, project_id, actor, program_link_id=None):
    project = _locked_project(project_id)
    team_policy.resolve_program_context(project, program_link_id)
    team_policy.require_mutable_team(project)
    _require_not_leader(project, actor.pk)
    _locked_member(project, actor.pk).delete()


@transaction.atomic
def switch_leader(*, project_id, user_id, actor, program_link_id=None):
    project = _locked_project(project_id)
    require_team_manager(project, actor)
    team_policy.validate_new_member(project, user_id, program_link_id=program_link_id)
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
def reject_direct_add(*, project_id, actor, program_link_id=None):
    project = _locked_project(project_id)
    require_team_manager(project, actor)
    team_policy.resolve_program_context(project, program_link_id)
    team_policy.require_mutable_team(project)
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


def _lock_invite(invite_id):
    reference = get_object_or_404(Invite.objects.only("project_id"), pk=invite_id)
    project = _locked_project(reference.project_id)
    # Повторное чтение после Project lock: revoke мог уже удалить запись.
    invite = get_object_or_404(Invite.objects.select_for_update(), pk=invite_id)
    return project, invite


def _invite_context(project, invite, program_link_id=None):
    if invite.program_link_id is not None:
        if program_link_id is not None and str(program_link_id) != str(
            invite.program_link_id
        ):
            raise TeamError(
                "invalid_program_context",
                "Приглашение относится к другой связи программы.",
                status_code=422,
            )
        program_link_id = invite.program_link_id
    return team_policy.resolve_program_context(project, program_link_id)


def _pending_invites(project, user_id):
    return Invite.objects.filter(
        project=project, user_id=user_id, is_accepted__isnull=True
    )


def _model_business_error(error):
    errors = (
        [item for values in error.error_dict.values() for item in values]
        if hasattr(error, "error_dict")
        else error.error_list
    )
    code = next((item.code for item in errors if item.code), "invalid_invite_fields")
    return TeamError(code, " ".join(error.messages))


@transaction.atomic
def create_invite(*, project_id, user_id, actor, program_link_id=None, **fields):
    project = _locked_project(project_id)
    require_team_manager(project, actor)
    link = team_policy.validate_new_member(
        project, user_id, program_link_id=program_link_id
    )
    _require_invite_eligible(project, user_id)
    pending = _pending_invites(project, user_id)
    if pending.exists():
        raise TeamError(
            "duplicate_pending_invite", "У пользователя уже есть активное приглашение."
        )
    try:
        # Savepoint нужен, чтобы после IntegrityError внешняя транзакция оставалась рабочей.
        with transaction.atomic():
            return Invite.objects.create(
                project=project, user_id=user_id, program_link=link, **fields
            )
    except DjangoValidationError as error:
        raise _model_business_error(error) from error
    except IntegrityError as error:
        if pending.exists():
            raise TeamError(
                "duplicate_pending_invite",
                "У пользователя уже есть активное приглашение.",
            ) from error
        raise


@transaction.atomic
def edit_pending_invite(*, invite_id, actor, program_link_id=None, **fields):
    project, invite = _lock_invite(invite_id)
    require_team_manager(project, actor)
    _require_pending(invite)
    link = _invite_context(project, invite, program_link_id)
    team_policy.require_mutable_team(project)
    team_policy.validate_new_member(
        project, invite.user_id, program_link_id=link.pk if link else None
    )
    allowed_fields = {"role", "specialization", "motivational_letter"}
    if fields.keys() - allowed_fields:
        raise TeamError(
            "invalid_invite_fields", "Недопустимые поля приглашения.", status_code=422
        )
    for field, value in fields.items():
        setattr(invite, field, value)
    if fields or invite.program_link_id != (link.pk if link else None):
        invite.program_link = link
        try:
            invite.save(update_fields=[*fields, "program_link", "datetime_updated"])
        except DjangoValidationError as error:
            raise _model_business_error(error) from error
    return invite


@transaction.atomic
def accept_invite(*, invite_id, actor, program_link_id=None):
    project, invite = _lock_invite(invite_id)
    _require_recipient(invite, actor)
    _require_pending(invite)
    link = _invite_context(project, invite, program_link_id)
    team_policy.validate_new_member(
        project, invite.user_id, program_link_id=link.pk if link else None
    )
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
    invite.program_link = link
    invite.save(update_fields=["is_accepted", "program_link", "datetime_updated"])
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


@transaction.atomic
def add_member(
    *,
    project_id,
    user_id,
    actor,
    role=None,
    specialization=None,
    program_link_id=None,
    allow_staff=False
):
    project = _locked_project(project_id)
    if not (allow_staff and (actor.is_staff or actor.is_superuser)):
        require_team_manager(project, actor)
    team_policy.validate_new_member(project, user_id, program_link_id=program_link_id)
    _require_invite_eligible(project, user_id)
    try:
        with transaction.atomic():
            return Collaborator.objects.create(
                project=project, user_id=user_id, role=role, specialization=specialization
            )
    except DjangoValidationError as error:
        raise TeamError("invalid_team_member", " ".join(error.messages)) from error
    except IntegrityError as error:
        if Collaborator.objects.filter(project=project, user_id=user_id).exists():
            raise TeamError(
                "already_project_member", "Пользователь уже состоит в проекте."
            ) from error
        raise


@transaction.atomic
def bind_project_to_program(*, project_id, program_id, actor, program_link_id=None):
    if program_id is None:
        return
    try:
        program_id = int(program_id)
    except (TypeError, ValueError):
        raise TeamError(
            "invalid_program_context", "Укажите корректную программу.", status_code=422
        )
    context = team_policy.lock_team(
        project_id, extra_program_ids=[program_id] if program_id else []
    )
    project = context.project
    require_team_manager(project, actor)
    current_link = team_policy.resolve_program_context(project, program_link_id)
    team_policy.require_mutable_team(project)
    program = context.programs.get(program_id) if program_id else None
    if program_id and program is None:
        raise TeamError(
            "invalid_program_context", "Программа не найдена.", status_code=422
        )
    if program:
        if (
            not program.is_project_submission_open()
            or program.datetime_finished < timezone.now()
        ):
            raise TeamError(
                "submission_closed", "Срок подачи проектов в программу завершён."
            )
        if (
            not program.is_manager(actor)
            and not PartnerProgramUserProfile.objects.filter(
                partner_program=program, user=actor
            ).exists()
        ):
            raise TeamError(
                "not_program_member",
                "Подача проекта доступна только участникам программы.",
            )
        team_policy.validate_project_binding(project, program)
    if current_link and current_link.partner_program_id != program_id:
        if current_link.team_invites.exists():
            raise TeamError(
                "program_context_in_use",
                "Связь программы используется приглашениями; её нельзя удалить.",
            )
        PartnerProgramUserProfile.objects.filter(
            project=project, partner_program_id=current_link.partner_program_id
        ).update(project=None)
        current_link.delete()
    if program:
        link, _created = PartnerProgramProject.objects.get_or_create(
            project=project, partner_program=program
        )
        project.is_public = False
        project.save(update_fields=["is_public"])
        PartnerProgramUserProfile.objects.filter(
            user=actor, partner_program=program
        ).update(project=project)
        return link
