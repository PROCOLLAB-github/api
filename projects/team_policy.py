"""Общие правила legacy-команды; HTTP-адаптеры не выбирают программу сами."""

from dataclasses import dataclass

from django.db import connection
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from invites.models import Invite
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramUserProfile,
)
from projects.models import Collaborator, Project
from projects.team_errors import TeamError


@dataclass
class TeamContext:
    project: Project
    links: list
    programs: dict


def lock_team(project_id, *, extra_program_ids=()):
    """Вызывать внутри atomic. Project защищает также добавление/удаление links."""
    project = get_object_or_404(Project.objects.select_for_update(), pk=project_id)
    program_ids = set(
        project.program_links.values_list("partner_program_id", flat=True)
    ) | set(extra_program_ids)
    programs = {
        program.pk: program
        for program in PartnerProgram.objects.select_for_update()
        .filter(pk__in=program_ids)
        .order_by("pk")
    }
    links = list(project.program_links.select_for_update().order_by("pk"))
    for link in links:
        link.project = project
        link.partner_program = programs[link.partner_program_id]
    context = TeamContext(project, links, programs)
    project._team_context = context
    return context


def context_for(project):
    context = getattr(project, "_team_context", None)
    if context is not None:
        return context
    cached = getattr(project, "_prefetched_objects_cache", {}).get("program_links")
    links = (
        list(cached)
        if cached is not None
        else list(project.program_links.select_related("partner_program").order_by("pk"))
    )
    return TeamContext(
        project, links, {link.partner_program_id: link.partner_program for link in links}
    )


def resolve_program_context(project, program_link_id=None):
    links = context_for(project).links
    if program_link_id is None:
        program_link_id = getattr(project, "_team_program_link_id", None)
    if program_link_id is not None:
        try:
            program_link_id = int(program_link_id)
        except (ValueError, TypeError):
            raise TeamError(
                "invalid_program_context",
                "Укажите корректный ID связи программы.",
                status_code=422,
            )
        for link in links:
            if link.pk == program_link_id:
                project._team_program_link_id = link.pk
                return link
        raise TeamError(
            "invalid_program_context",
            "Связь программы не принадлежит этому проекту.",
            status_code=422,
        )
    if len(links) > 1:
        raise TeamError(
            "program_context_required", "Укажите конкретную связь проекта с программой."
        )
    return links[0] if links else None


def require_mutable_team(project):
    if any(
        link.submitted and link.partner_program.is_competitive
        for link in context_for(project).links
    ):
        raise TeamError("team_frozen", "Состав команды зафиксирован после сдачи проекта.")


def accepted_user_ids(project):
    return set(project.collaborator_set.values_list("user_id", flat=True)) | {
        project.leader_id
    }


def reserved_user_ids(project):
    return accepted_user_ids(project) | set(
        Invite.objects.filter(project=project, is_accepted__isnull=True).values_list(
            "user_id", flat=True
        )
    )


def has_active_exclusivity(program):
    return program.is_competitive and program.datetime_finished > timezone.now()


def conflicting_team_users(program, *, project_id, user_ids):
    if not has_active_exclusivity(program):
        return set()
    other_projects = Project.objects.filter(
        program_links__partner_program=program
    ).exclude(pk=project_id)
    return set(
        other_projects.filter(leader_id__in=user_ids).values_list("leader_id", flat=True)
    ) | set(
        Collaborator.objects.filter(
            project__in=other_projects, user_id__in=user_ids
        ).values_list("user_id", flat=True)
    )


def validate_program_users(program, *, project_id, user_ids, lock=False):
    memberships = PartnerProgramUserProfile.objects.filter(
        partner_program=program, user_id__in=user_ids
    )
    if lock:
        memberships = memberships.select_for_update().order_by("pk")
    registered = set(memberships.values_list("user_id", flat=True))
    if set(user_ids) - registered:
        raise TeamError(
            "not_program_member",
            "Каждый участник команды должен быть зарегистрирован в программе.",
        )
    if conflicting_team_users(program, project_id=project_id, user_ids=user_ids):
        raise TeamError(
            "already_in_program_team",
            "Пользователь уже состоит в другой команде этой программы.",
        )


def validate_max_size(program, user_ids):
    if (
        program.is_competitive
        and program.legacy_team_max_size is not None
        and len(user_ids) > program.legacy_team_max_size
    ):
        raise TeamError(
            "team_max_size",
            f"Максимальный размер команды — {program.legacy_team_max_size}; ожидающие приглашения резервируют места.",
        )


def validate_new_member(project, user_id, *, program_link_id=None):
    link = resolve_program_context(project, program_link_id)
    require_mutable_team(project)
    for program in context_for(project).programs.values():
        validate_program_users(
            program,
            project_id=project.pk,
            user_ids={user_id},
            lock=connection.in_atomic_block,
        )
        validate_max_size(program, reserved_user_ids(project) | {user_id})
    return link


def validate_submission_team(project, link):
    members = accepted_user_ids(project)
    validate_program_users(
        link.partner_program,
        project_id=project.pk,
        user_ids=members,
        lock=connection.in_atomic_block,
    )
    program = link.partner_program
    if (
        program.legacy_team_min_size is not None
        and len(members) < program.legacy_team_min_size
    ):
        raise TeamError(
            "team_min_size",
            f"Для сдачи проекта нужно не менее {program.legacy_team_min_size} участников.",
        )
    validate_max_size(program, members)
    return members


def validate_project_binding(project, program):
    require_mutable_team(project)
    if program.is_competitive:
        validate_program_users(
            program,
            project_id=project.pk,
            user_ids=accepted_user_ids(project),
            lock=connection.in_atomic_block,
        )
        validate_max_size(program, reserved_user_ids(project))


def validate_required_program_fields(link):
    from django.core.exceptions import ValidationError

    fields = link.partner_program.fields.filter(is_required=True).order_by("pk")
    if connection.in_atomic_block:
        fields = fields.select_for_update()
    required = list(fields)
    values = (
        dict(
            link.field_values.filter(field__in=required).values_list(
                "field_id", "value_text"
            )
        )
        if link.pk
        else {}
    )
    if any(
        field.pk not in values
        or values[field.pk] is None
        or not str(values[field.pk]).strip()
        for field in required
    ):
        raise ValidationError("Не заполнены обязательные поля программы.")


def actionable_users(project, users, *, program_link_id=None):
    resolve_program_context(project, program_link_id)
    try:
        require_mutable_team(project)
        reserved = reserved_user_ids(project)
        for program in context_for(project).programs.values():
            validate_max_size(program, reserved | {-1})
    except TeamError:
        return users.none()
    users = users.exclude(pk__in=reserved)
    for program in context_for(project).programs.values():
        users = users.filter(partner_program_profiles__partner_program=program)
        if has_active_exclusivity(program):
            others = Project.objects.filter(
                program_links__partner_program=program
            ).exclude(pk=project.pk)
            users = users.exclude(
                Q(pk__in=others.values("leader_id"))
                | Q(
                    pk__in=Collaborator.objects.filter(project__in=others).values(
                        "user_id"
                    )
                )
            )
    return users.distinct()


def validate_model_member(member):
    previous = Collaborator.objects.filter(pk=member.pk).first() if member.pk else None
    if previous and (
        previous.project_id != member.project_id or previous.user_id != member.user_id
    ):
        raise TeamError(
            "invalid_team_member",
            "Участника нельзя переназначить другому пользователю или проекту.",
        )
    changed = previous is None or any(
        getattr(previous, field) != getattr(member, field)
        for field in ("project_id", "user_id", "role", "specialization")
    )
    if changed:
        validate_new_member(
            member.project,
            member.user_id,
            program_link_id=getattr(member, "_program_link_id", None),
        )
    else:
        resolve_program_context(member.project, getattr(member, "_program_link_id", None))


def validate_model_leader(project):
    previous = Project.objects.filter(pk=project.pk).first() if project.pk else None
    if previous and previous.leader_id != project.leader_id:
        require_mutable_team(project)
        if not Collaborator.objects.filter(
            project=project, user_id=project.leader_id
        ).exists():
            raise TeamError(
                "collaborator_not_found",
                "Новый лидер должен быть участником команды.",
                status_code=422,
            )
        validate_new_member(project, project.leader_id)


def policy_snapshot(project):
    links = context_for(project).links
    return {
        "is_frozen": any(
            link.submitted and link.partner_program.is_competitive for link in links
        ),
        "program_link_id": links[0].pk if len(links) == 1 else None,
        "requires_program_context": len(links) > 1,
        "program_links": [
            {
                "id": link.pk,
                "program_id": link.partner_program_id,
                "is_submitted": link.submitted,
                "is_competitive": link.partner_program.is_competitive,
            }
            for link in links
        ],
    }
