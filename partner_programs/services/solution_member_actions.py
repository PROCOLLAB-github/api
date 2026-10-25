"""Confirmed organizer removal preserves materials, registration and evaluations."""

import copy
import hashlib
import json
import logging
from contextvars import ContextVar

from django.core import signing
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from partner_programs.permissions import can_manage_program
from partner_programs.solution_api import iso, mutation_receipt, user_data
from partner_programs.solution_errors import MAX_ID, SolutionError, issue
from partner_programs.solution_models import ProgramSolution, SolutionAdministrativeChange
from partner_programs.solution_team import program_for

SALT = "solution-member-removal-v1"
MAX_AGE = 600
logger = logging.getLogger(__name__)
_confirmed_deletion = ContextVar("solution_confirmed_member_deletion", default=None)


def permits_member_deletion(instance):
    # Only one exact row inside the confirmed writer's transaction. Ordinary
    # model/queryset/admin/cascade deletes never acquire this capability.
    return _confirmed_deletion.get() == (
        instance.solution_id,
        instance.pk,
        instance.user_id,
    )


def delete_confirmed_member(member):
    """Internal writer, after permission/proof recheck and program/solution locks."""
    token = _confirmed_deletion.set((member.solution_id, member.pk, member.user_id))
    try:
        member.delete()
    finally:
        _confirmed_deletion.reset(token)


def conflict(errors=None):
    return SolutionError(
        "solution_action_conflict",
        "Состав или данные решения изменились. Проверьте их и подтвердите действие заново.",
        errors=errors or [],
    )


def context(program_id, solution_id, actor):
    program = program_for(program_id, lock=True)
    if not can_manage_program(actor, program):
        raise SolutionError(
            "permission_denied", "Действие доступно организатору программы.", status=403
        )
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    if not 0 < solution_id <= MAX_ID:
        raise Http404
    try:
        solution = ProgramSolution.objects.select_for_update().get(
            program=program, pk=solution_id
        )
    except ProgramSolution.DoesNotExist:
        raise Http404
    solution.program = program
    members = list(
        solution.members.select_for_update(of=("self",))
        .select_related("user")
        .order_by("pk")
    )
    invitations = list(solution.invitations.select_for_update().order_by("pk"))
    return program, solution, members, invitations


def inspect(program, solution, members, invitations, user_id):
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or not 0 < user_id <= MAX_ID
    ):
        raise SolutionError(
            "validation_error", "Укажите корректного участника.", status=400
        )
    member = next((m for m in members if m.user_id == user_id), None)
    if member is None:
        raise Http404
    removed_member = dict(
        user=user_data(member.user),
        role=member.role,
        specialization=member.specialization,
        joined_at=iso(member.joined_at),
        is_captain=member.user_id == solution.captain_id,
    )
    errors = []
    if solution.status == "submitted":
        saved = next(
            (
                m
                for m in solution.submission_snapshot["members"]
                if m["user"]["id"] == user_id
            ),
            None,
        )
        if saved is None:
            errors.append(
                issue("user_id", "team_state_changed", "Состав решения требует проверки.")
            )
        else:
            removed_member = copy.deepcopy(saved)
    if member.user_id == solution.captain_id:
        errors.append(
            issue(
                "user_id",
                "captain_cannot_be_removed",
                "Капитана нельзя исключить из состава. Для него снимите заявку с участия.",
            )
        )
    pending = [
        row.pk
        for row in invitations
        if row.recipient_id == user_id and row.status == "pending"
    ]
    scores = list(
        solution.scores.order_by("pk").values("id", "criteria_id", "user_id", "value")
    )
    state = dict(
        program=[program.pk, program.solution_storage_mode, program.is_competitive],
        solution=list(ProgramSolution.objects.filter(pk=solution.pk).values()),
        members=[
            dict(
                id=m.pk,
                user_id=m.user_id,
                role=m.role,
                specialization=m.specialization,
                joined_at=m.joined_at,
                user=user_data(m.user),
            )
            for m in members
        ],
        invitations=[
            dict(
                id=i.pk,
                recipient_id=i.recipient_id,
                status=i.status,
                role=i.role,
                specialization=i.specialization,
                motivational_letter=i.motivational_letter,
                version=i.version,
                updated_at=i.updated_at,
            )
            for i in invitations
        ],
        answers=list(solution.answers.order_by("pk").values()),
        assignments=list(solution.expert_assignments.order_by("pk").values()),
        scores=scores,
    )
    digest = hashlib.sha256(
        json.dumps(state, sort_keys=True, default=str).encode()
    ).hexdigest()
    return (
        dict(
            application=dict(
                kind="solution",
                program_id=program.pk,
                solution_id=solution.pk,
                name=solution.name,
            ),
            member=removed_member,
            solution_version=solution.version,
            is_submitted=solution.status == "submitted",
            remaining_member_count=len(members) - 1,
            revoked_invitation_count=len(pending),
            score_count=len(scores),
            errors=errors,
            can_apply=not errors,
        ),
        digest,
        member,
        pending,
    )


def proof_context(program, solution, actor, user_id):
    return dict(actor=actor.pk, program=program.pk, solution=solution.pk, user=user_id)


@transaction.atomic
def preview(program_id, solution_id, actor, data):
    program, solution, members, invitations = context(program_id, solution_id, actor)
    result, state, _, _ = inspect(
        program, solution, members, invitations, data["user_id"]
    )
    result["preview_token"] = (
        signing.dumps(
            {**proof_context(program, solution, actor, data["user_id"]), "state": state},
            salt=SALT,
            compress=True,
        )
        if result["can_apply"]
        else None
    )
    return result


@transaction.atomic
def apply(program_id, solution_id, actor, data):
    program, solution, members, invitations = context(program_id, solution_id, actor)
    try:
        proof = signing.loads(data["preview_token"], salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as error:
        raise conflict() from error
    expected = proof_context(program, solution, actor, data["user_id"])
    if not isinstance(proof, dict) or any(proof.get(k) != v for k, v in expected.items()):
        raise conflict()
    if not any(m.user_id == data["user_id"] for m in members):
        # Replaying a consumed confirmation is a conflict; a fresh preview of
        # an absent member is 404. Do not make a second revision.
        raise conflict()
    result, state, member, pending = inspect(
        program, solution, members, invitations, data["user_id"]
    )
    if proof.get("state") != state or not result["can_apply"]:
        raise conflict(result["errors"])
    before_version = solution.version
    before_snapshot = copy.deepcopy(solution.submission_snapshot)
    delete_confirmed_member(member)
    solution.invitations.filter(pk__in=pending, status="pending").delete()
    if solution.status == "submitted":
        after = copy.deepcopy(before_snapshot)
        after["members"] = [
            m for m in after["members"] if m["user"]["id"] != data["user_id"]
        ]
        solution.submission_snapshot = after
    solution.version += 1
    solution.updated_at = timezone.now()
    # Explicit privileged writer; ordinary save/model/admin guards stay frozen.
    ProgramSolution.objects.filter(pk=solution.pk).update(
        version=solution.version,
        updated_at=solution.updated_at,
        submission_snapshot=solution.submission_snapshot,
    )
    SolutionAdministrativeChange.objects.create(
        solution=solution,
        actor=actor,
        actor_name=f"{actor.first_name} {actor.last_name}".strip(),
        action="remove_member",
        before_version=before_version,
        after_version=solution.version,
        removed_member=copy.deepcopy(result["member"]),
        revoked_invitation_ids=pending,
        score_count=result["score_count"],
        was_submitted=solution.status == "submitted",
        before_snapshot=before_snapshot,
        after_snapshot=copy.deepcopy(solution.submission_snapshot),
    )
    logger.info(
        "Program solution member removal program=%s actor=%s solution=%s user=%s",
        program.pk,
        actor.pk,
        solution.pk,
        data["user_id"],
    )
    return mutation_receipt(solution)
