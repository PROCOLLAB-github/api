"""Confirmed registration removal, with retained work and program-scoped audit."""

import copy
import hashlib
import json

from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from invites.models import Invite
from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.permissions import can_manage_program
from partner_programs.services import solution_archive_actions as archive
from partner_programs.services.solution_member_actions import delete_confirmed_member
from partner_programs.solution_api import solution_data, user_data
from partner_programs.solution_errors import MAX_ID, SolutionError, issue
from partner_programs.solution_models import (
    ProgramSolution,
    SolutionAdministrativeChange,
    SolutionRegistrationRemoval,
)
from partner_programs.solution_team import program_for
from projects.models import Collaborator

SALT = "solution-registration-removal-v1"
MAX_AGE = 600


def managed_program(program_id, actor, *, lock=False):
    program = program_for(program_id, lock=lock)
    if not can_manage_program(actor, program):
        raise SolutionError(
            "permission_denied", "Действие доступно организатору программы.", status=403
        )
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    return program


def context(program_id, actor, ids, *, applying=False):
    program = managed_program(program_id, actor, lock=True)
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 10000
        or any(type(pk) is not int or not 0 < pk <= MAX_ID for pk in ids)
        or len(set(ids)) != len(ids)
    ):
        raise SolutionError(
            "validation_error", "Выберите регистрации без повторов.", status=400
        )
    profiles = list(
        PartnerProgramUserProfile.objects.select_for_update(of=("self",))
        .filter(partner_program=program, pk__in=ids, user__isnull=False)
        .select_related("user")
        .order_by("pk")
    )
    if len(profiles) != len(ids):
        if applying:
            raise archive.conflict()
        raise Http404
    users = [p.user_id for p in profiles]
    legacy = PartnerProgramProject.objects.filter(partner_program=program).filter(
        Q(project__leader_id__in=users)
        | Q(
            project_id__in=Collaborator.objects.filter(user_id__in=users).values(
                "project_id"
            )
        )
        | Q(project_id__in=Invite.objects.filter(user_id__in=users).values("project_id"))
    )
    if any(p.project_id is not None for p in profiles) or legacy.exists():
        raise SolutionError(
            "legacy_application_conflict",
            "Регистрация связана с заявкой проекта. Удаление отменено для сохранения данных.",
        )
    ids = list(
        ProgramSolution.objects.filter(program=program)
        .filter(
            Q(captain_id__in=users)
            | Q(members__user_id__in=users)
            | Q(invitations__recipient_id__in=users, invitations__status="pending")
        )
        .order_by("pk")
        .values_list("pk", flat=True)
        .distinct()
    )
    if not ids:
        return program, profiles, [], []
    _, rows, files = archive.context(program_id, actor, ids)
    return program, profiles, rows, files


def inspect(program, profiles, rows, actor, files):
    users = {p.user_id for p in profiles}
    registrations = [dict(registration_id=p.pk, user=user_data(p.user)) for p in profiles]
    effects, errors = [], []
    for solution in rows:
        data = solution_data(solution, actor)
        captain = solution.captain_id in users
        removed = [m for m in data["team"]["members"] if m["user"]["id"] in users]
        actual = set(
            solution.members.filter(user_id__in=users).values_list("user_id", flat=True)
        )
        if not captain and actual != {m["user"]["id"] for m in removed}:
            errors.append(
                issue(
                    "registration_ids",
                    "team_state_changed",
                    "Состав решения требует проверки.",
                )
            )
        pending = solution.invitations.filter(status="pending")
        effects.append(
            dict(
                application=dict(
                    kind="solution",
                    program_id=program.pk,
                    solution_id=solution.pk,
                    name=data["name"],
                ),
                solution_version=solution.version,
                is_submitted=solution.status == "submitted",
                effect="archive"
                if captain
                else "remove_members"
                if removed
                else "revoke_invitations",
                removed_members=[] if captain else removed,
                removed_assignments_count=solution.expert_assignments.count()
                if captain
                else 0,
                revoked_invitation_count=(
                    pending if captain else pending.filter(recipient_id__in=users)
                ).count(),
                score_count=solution.scores.count(),
            )
        )
    _, work_state = archive.inspect(program, rows, actor, files)
    state = hashlib.sha256(
        json.dumps(
            dict(
                work=work_state,
                effects=effects,
                people=registrations,
                registrations=list(
                    PartnerProgramUserProfile.objects.filter(
                        pk__in=[p.pk for p in profiles]
                    )
                    .order_by("pk")
                    .values()
                ),
            ),
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    result = dict(
        registrations=registrations,
        effects=effects,
        deleted_count=len(profiles),
        archived_count=sum(e["effect"] == "archive" for e in effects),
        removed_member_count=sum(len(e["removed_members"]) for e in effects),
        removed_assignments_count=sum(e["removed_assignments_count"] for e in effects),
        revoked_invitation_count=sum(e["revoked_invitation_count"] for e in effects),
        score_count=sum(e["score_count"] for e in effects),
        can_apply=not errors,
        errors=errors,
    )
    return result, state


def proof_context(program, actor, ids):
    return dict(program=program.pk, actor=actor.pk, registration_ids=sorted(ids))


@transaction.atomic
def preview(program_id, actor, data):
    program, profiles, rows, files = context(program_id, actor, data["registration_ids"])
    result, state = inspect(program, profiles, rows, actor, files)
    result["preview_token"] = (
        signing.dumps(
            {**proof_context(program, actor, data["registration_ids"]), "state": state},
            salt=SALT,
            compress=True,
        )
        if result["can_apply"]
        else None
    )
    return result


@transaction.atomic
def apply(program_id, actor, data):
    program, profiles, rows, files = context(
        program_id, actor, data["registration_ids"], applying=True
    )
    try:
        proof = signing.loads(data["preview_token"], salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as error:
        raise archive.conflict() from error
    expected = proof_context(program, actor, data["registration_ids"])
    if not isinstance(proof, dict) or any(proof.get(k) != v for k, v in expected.items()):
        raise archive.conflict()
    result, state = inspect(program, profiles, rows, actor, files)
    if not result["can_apply"] or proof.get("state") != state:
        raise archive.conflict()
    audit = SolutionRegistrationRemoval.objects.create(
        program=program,
        actor=actor,
        actor_name=f"{actor.first_name} {actor.last_name}".strip(),
        registrations=copy.deepcopy(result["registrations"]),
        deleted_count=len(profiles),
    )
    users, now, items = {p.user_id for p in profiles}, timezone.now(), []
    for solution, effect in zip(rows, result["effects"]):
        if effect["effect"] == "archive":
            item, change = archive.archive_locked(
                solution,
                actor,
                now,
                reason="registration_removed",
                registration_removal=audit,
            )
        else:
            before = copy.deepcopy(solution.submission_snapshot)
            for member in solution.members.filter(user_id__in=users).order_by("pk"):
                delete_confirmed_member(member)
            pending = list(
                solution.invitations.filter(recipient_id__in=users, status="pending")
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            solution.invitations.filter(pk__in=pending, status="pending").delete()
            after = copy.deepcopy(before)
            if after is not None:
                after["members"] = [
                    m for m in after["members"] if m["user"]["id"] not in users
                ]
            ProgramSolution.objects.filter(pk=solution.pk).update(
                submission_snapshot=after,
                version=solution.version + 1,
                updated_at=now,
            )
            change = SolutionAdministrativeChange.objects.create(
                solution=solution,
                actor=actor,
                actor_name=audit.actor_name,
                action="remove_registrations",
                registration_removal=audit,
                before_version=solution.version,
                after_version=solution.version + 1,
                removed_members=copy.deepcopy(effect["removed_members"]),
                revoked_invitation_ids=pending,
                score_count=effect["score_count"],
                was_submitted=solution.status == "submitted",
                before_snapshot=before,
                after_snapshot=after,
            )
            item = dict(
                application=effect["application"], solution_version=solution.version + 1
            )
        items.append(
            dict(
                application=item["application"],
                solution_version=item["solution_version"],
                change_id=change.pk,
                action=change.action,
            )
        )
    PartnerProgramUserProfile.objects.filter(
        partner_program=program, pk__in=data["registration_ids"]
    ).delete()
    return dict(audit_id=audit.pk, deleted_count=len(profiles), items=items)
