"""Signed withdrawal retains work independently of active program participation."""

import copy
import hashlib
import json
import logging

from django.core import signing
from django.db import models, transaction
from django.http import Http404
from django.utils import timezone

from files.models import UserFile
from partner_programs.permissions import can_manage_program
from partner_programs.solution_api import iso, solution_data
from partner_programs.solution_errors import MAX_ID, SolutionError, issue
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionMember,
    SolutionAdministrativeChange,
    SolutionInvitation,
)
from partner_programs.solution_team import program_for
from project_rates.solution_models import SolutionExpertAssignment

SALT = "solution-archive-actions-v1"
MAX_AGE = 600
logger = logging.getLogger(__name__)


def conflict():
    return SolutionError(
        "solution_action_conflict",
        "Данные решений изменились. Проверьте их и подтвердите действие заново.",
    )


def context(program_id, actor, ids):
    program = program_for(program_id, lock=True)
    if not can_manage_program(actor, program):
        raise SolutionError(
            "permission_denied", "Действие доступно организатору программы.", status=403
        )
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 10000
        or any(
            isinstance(pk, bool) or not isinstance(pk, int) or not 0 < pk <= MAX_ID
            for pk in ids
        )
        or len(ids) != len(set(ids))
    ):
        raise SolutionError(
            "validation_error", "Выберите корректные решения без повторов.", status=400
        )
    rows = list(
        ProgramSolution.all_objects.select_for_update()
        .filter(program=program, pk__in=ids)
        .order_by("pk")
    )
    if len(rows) != len(ids):
        raise Http404
    list(program.fields.select_for_update().order_by("pk"))
    list(
        ProgramSolutionMember.objects.select_for_update()
        .filter(solution__in=rows)
        .order_by("pk")
    )
    list(
        SolutionInvitation.objects.select_for_update()
        .filter(solution__in=rows)
        .order_by("pk")
    )
    urls = {
        a.value["url"]
        for row in rows
        for a in row.answers.all()
        if isinstance(a.value, dict) and isinstance(a.value.get("url"), str)
    }
    files = list(
        UserFile.objects.select_for_update().filter(pk__in=urls).order_by("pk").values()
    )
    for row in rows:
        row.program = program
    return program, rows, files


def inspect(program, rows, actor, files):
    items, state = [], []
    for solution in rows:
        errors = (
            [issue("ids", "solution_archived", "Решение уже снято с участия.")]
            if solution.archived_at
            else []
        )
        data = solution_data(solution, actor)
        assignments = list(solution.expert_assignments.order_by("pk").values())
        scores = list(solution.scores.order_by("pk").values())
        invitations = list(solution.invitations.order_by("pk").values())
        items.append(
            dict(
                application=dict(
                    kind="solution",
                    program_id=program.pk,
                    solution_id=solution.pk,
                    name=data["name"],
                ),
                solution_version=solution.version,
                is_submitted=solution.status == "submitted",
                is_archived=solution.archived_at is not None,
                score_count=len(scores),
                removed_assignments_count=len(assignments),
                revoked_invitation_count=sum(
                    i["status"] == "pending" for i in invitations
                ),
                errors=errors,
            )
        )
        state.append(
            dict(
                solution=list(
                    ProgramSolution.all_objects.filter(pk=solution.pk).values()
                ),
                material=data,
                answers=list(solution.answers.order_by("pk").values()),
                members=list(solution.members.order_by("pk").values()),
                assignments=assignments,
                scores=scores,
                invitations=invitations,
            )
        )
    digest = hashlib.sha256(
        json.dumps(
            dict(
                program=[
                    program.pk,
                    program.solution_storage_mode,
                    program.is_competitive,
                ],
                rows=state,
                files=files,
            ),
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    return (
        dict(
            items=items,
            score_count=sum(i["score_count"] for i in items),
            removed_assignments_count=sum(i["removed_assignments_count"] for i in items),
            revoked_invitation_count=sum(i["revoked_invitation_count"] for i in items),
            can_apply=not any(i["errors"] for i in items),
        ),
        digest,
    )


def proof_context(program, actor, ids):
    return dict(program=program.pk, actor=actor.pk, ids=sorted(ids))


@transaction.atomic
def preview(program_id, actor, data):
    program, rows, files = context(program_id, actor, data["ids"])
    result, state = inspect(program, rows, actor, files)
    result["preview_token"] = (
        signing.dumps(
            {**proof_context(program, actor, data["ids"]), "state": state},
            salt=SALT,
            compress=True,
        )
        if result["can_apply"]
        else None
    )
    return result


def archive_locked(solution, actor, now, *, reason="detached", registration_removal=None):
    """Internal writer after authorization/proof recheck and all context locks."""
    if solution.archived_at is not None or reason not in (
        "detached",
        "registration_removed",
    ):
        raise conflict()
    if (reason == "registration_removed") != (registration_removal is not None):
        raise conflict()
    before = copy.deepcopy(solution.submission_snapshot)
    version = solution.version
    saved = solution_data(solution, actor)
    form = copy.deepcopy(saved["form"])
    form["is_snapshot"] = True
    captured = dict(
        name=saved["name"],
        captain_id=saved["captain_id"],
        members=copy.deepcopy(saved["team"]["members"]),
        form=form,
        answers=copy.deepcopy(saved["answers"]),
        captured_at=iso(now),
    )
    pending = list(
        solution.invitations.filter(status="pending")
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    removed = list(
        solution.expert_assignments.order_by("pk").values_list("pk", flat=True)
    )
    score_count = solution.scores.count()
    solution.invitations.filter(pk__in=pending, status="pending").delete()
    # The approved detach exception removes even scored assignments, as the
    # legacy program-link writer does. Scope is the confirmed locked rows;
    # normal SolutionAssignmentQuerySet.delete keeps its score protection.
    models.QuerySet.delete(
        SolutionExpertAssignment.objects.filter(solution=solution, pk__in=removed)
    )
    changed = ProgramSolution.all_objects.filter(
        pk=solution.pk, archived_at__isnull=True
    ).update(
        archived_at=now,
        archived_by=actor,
        archive_reason=reason,
        archive_snapshot=captured,
        version=version + 1,
        updated_at=now,
    )
    if changed != 1:
        raise conflict()
    change = SolutionAdministrativeChange.objects.create(
        solution=solution,
        actor=actor,
        actor_name=f"{actor.first_name} {actor.last_name}".strip(),
        action="archive",
        registration_removal=registration_removal,
        before_version=version,
        after_version=version + 1,
        removed_assignment_ids=removed,
        revoked_invitation_ids=pending,
        score_count=score_count,
        was_submitted=solution.status == "submitted",
        before_snapshot=before,
        after_snapshot=copy.deepcopy(before),
        archived_at=now,
        archive_reason=reason,
        archive_snapshot=copy.deepcopy(captured),
    )
    return (
        dict(
            application=dict(
                kind="solution",
                program_id=solution.program_id,
                solution_id=solution.pk,
                name=captured["name"],
            ),
            solution_version=version + 1,
            archived_at=iso(now),
        ),
        change,
    )


@transaction.atomic
def apply(program_id, actor, data):
    program, rows, files = context(program_id, actor, data["ids"])
    try:
        proof = signing.loads(data["preview_token"], salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as error:
        raise conflict() from error
    expected = proof_context(program, actor, data["ids"])
    if not isinstance(proof, dict) or any(proof.get(k) != v for k, v in expected.items()):
        raise conflict()
    result, state = inspect(program, rows, actor, files)
    if not result["can_apply"] or proof.get("state") != state:
        raise conflict()
    now = timezone.now()
    items = []
    for solution in rows:
        item, _ = archive_locked(solution, actor, now)
        items.append(item)
    logger.info(
        "Program solution archive program=%s actor=%s solutions=%s",
        program.pk,
        actor.pk,
        data["ids"],
    )
    return dict(changed_count=len(items), items=items)
