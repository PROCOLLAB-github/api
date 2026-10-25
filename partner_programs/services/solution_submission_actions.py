"""Existing organizer first-submission exception, bound to a signed preview."""

import hashlib
import json
import logging

from django.core import signing
from django.db import transaction
from django.http import Http404

from files.models import UserFile
from partner_programs.models import PartnerProgramUserProfile
from partner_programs.permissions import can_manage_program
from partner_programs.solution_api import user_data
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_models import ProgramSolution, ProgramSolutionMember
from partner_programs.solution_schema import form_data
from partner_programs.solution_submission import _finalize_submission, readiness_issues
from partner_programs.solution_team import program_for
from project_rates.solution_evaluation import snapshot_name

SALT = "solution-submission-actions-v1"
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
            "permission_denied",
            "Действие доступно организатору программы.",
            status=403,
        )
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    if not program.is_competitive:
        raise SolutionError(
            "not_competitive", "В программе нет сдачи конкурсных решений."
        )
    rows = list(
        ProgramSolution.objects.select_for_update(of=("self",))
        .filter(program=program, pk__in=ids)
        .select_related("captain")
        .prefetch_related("answers", "members__user", "invitations")
        .order_by("pk")
    )
    if len(rows) != len(ids):
        raise Http404
    list(program.fields.select_for_update().order_by("pk"))
    list(
        ProgramSolutionMember.objects.select_for_update()
        .filter(solution_id__in=ids)
        .order_by("pk")
    )
    urls = {
        answer.value["url"]
        for row in rows
        for answer in row.answers.all()
        if isinstance(answer.value, dict) and isinstance(answer.value.get("url"), str)
    }
    # File metadata can have writers outside the solution commands. Bind the
    # preview fingerprint under the same locks held until snapshot commit.
    list(UserFile.objects.select_for_update().filter(pk__in=urls).order_by("pk"))
    for row in rows:
        row.program = program
    return program, rows


def inspect(program, rows):
    form = form_data(program)
    items, state, ready, already = [], [], 0, 0
    users, urls = set(), set()
    for solution in rows:
        answers = [
            dict(field_id=row.field_id, value=row.value)
            for row in sorted(solution.answers.all(), key=lambda row: row.field_id)
        ]
        members = [
            dict(
                user=user_data(member.user),
                role=member.role,
                specialization=member.specialization,
                joined_at=member.joined_at,
            )
            for member in sorted(solution.members.all(), key=lambda row: row.pk)
        ]
        accepted = [member["user"]["id"] for member in members]
        users.update(accepted)
        urls.update(
            row["value"]["url"]
            for row in answers
            if isinstance(row["value"], dict) and isinstance(row["value"].get("url"), str)
        )
        errors = (
            []
            if solution.status == "submitted"
            else readiness_issues(solution, form, answers, accepted)
        )
        items.append(
            dict(
                application=dict(
                    kind="solution",
                    program_id=program.pk,
                    solution_id=solution.pk,
                    name=snapshot_name(solution),
                ),
                errors=errors,
            )
        )
        already += int(solution.status == "submitted")
        ready += int(solution.status == "draft" and not errors)
        state.append(
            dict(
                id=solution.pk,
                version=solution.version,
                name=solution.name,
                captain=solution.captain_id,
                status=solution.status,
                submitted_at=solution.submitted_at,
                snapshot=solution.submission_snapshot,
                answers=answers,
                members=members,
                invitations=[
                    dict(
                        id=row.pk,
                        version=row.version,
                        status=row.status,
                        recipient=row.recipient_id,
                    )
                    for row in sorted(solution.invitations.all(), key=lambda row: row.pk)
                ],
            )
        )
    fingerprint = dict(
        program=program.pk,
        form=form,
        minimum=program.legacy_team_min_size,
        maximum=program.legacy_team_max_size,
        solutions=state,
        registrations=list(
            PartnerProgramUserProfile.objects.filter(
                partner_program=program, user_id__in=users
            )
            .order_by("pk")
            .values("id", "user_id")
        ),
        files=list(
            UserFile.objects.filter(pk__in=urls)
            .order_by("pk")
            .values("link", "user_id", "size", "extension", "detected_mime_type")
        ),
    )
    digest = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True, default=str).encode()
    ).hexdigest()
    result = dict(
        items=items,
        ready_count=ready,
        already_submitted_count=already,
        can_apply=ready > 0 and not any(item["errors"] for item in items),
    )
    return result, digest, form


def proof_context(program, actor, data):
    return dict(
        actor=actor.pk, program=program.pk, ids=data["ids"], action=data["action"]
    )


@transaction.atomic
def preview(program_id, actor, data):
    program, rows = context(program_id, actor, data["ids"])
    result, state, _ = inspect(program, rows)
    result["preview_token"] = (
        signing.dumps(
            {**proof_context(program, actor, data), "state": state},
            salt=SALT,
            compress=True,
        )
        if result["can_apply"]
        else None
    )
    return result


@transaction.atomic
def apply(program_id, actor, data):
    program, rows = context(program_id, actor, data["ids"])
    try:
        proof = signing.loads(data["preview_token"], salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as error:
        raise conflict() from error
    if not isinstance(proof, dict) or any(
        proof.get(key) != value
        for key, value in proof_context(program, actor, data).items()
    ):
        raise conflict()
    result, state, form = inspect(program, rows)
    if proof.get("state") != state or not result["can_apply"]:
        raise conflict()
    for solution in rows:
        if solution.status == "draft":
            _finalize_submission(solution, actor, form, allow_after_deadline=True)
    logger.info(
        "Program solution submission action program=%s actor=%s ids=%s changed=%s already=%s",
        program.pk,
        actor.pk,
        data["ids"],
        result["ready_count"],
        result["already_submitted_count"],
    )
    return dict(
        changed_count=result["ready_count"],
        already_submitted_count=result["already_submitted_count"],
    )
