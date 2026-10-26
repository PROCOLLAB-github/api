"""Confirmed organizer case changes retain the original submission in history."""

import copy
import hashlib
import json
import logging

from django.core import signing
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from partner_programs.permissions import can_manage_program
from partner_programs.solution_api import mutation_receipt
from partner_programs.solution_errors import MAX_ID, SolutionError, issue
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionAdministrativeChange,
)
from partner_programs.solution_schema import form_data
from partner_programs.solution_team import (
    advance_version,
    program_for,
)
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore

SALT = "solution-case-actions-v1"
MAX_AGE = 600
logger = logging.getLogger(__name__)


def conflict(errors=None):
    return SolutionError(
        "solution_action_conflict",
        "Данные решения изменились. Проверьте их и подтвердите действие заново.",
        errors=errors or [],
    )


def context(program_id, solution_id, actor):
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
    if not 0 < solution_id <= MAX_ID:
        raise Http404
    try:
        solution = ProgramSolution.objects.select_for_update().get(
            program=program, pk=solution_id
        )
    except ProgramSolution.DoesNotExist:
        raise Http404
    solution.program = program
    list(program.fields.select_for_update().order_by("pk"))
    list(solution.answers.select_for_update().order_by("pk"))
    list(solution.members.select_for_update().order_by("pk"))
    form = form_data(program)
    field = next((f for f in form["fields"] if f["purpose"] == "case"), None)
    if not form["is_configured"] or field is None:
        raise SolutionError("form_not_configured", "Организатор еще не настроил форму.")
    return program, solution, form, field


def applied_field(solution, field):
    if solution.status == "submitted":
        saved = next(
            (
                item
                for item in solution.submission_snapshot["form"]["fields"]
                if item["purpose"] == "case"
            ),
            None,
        )
        if saved and solution.program.fields.filter(pk=saved["id"]).exists():
            return saved
    return field


def inspect(program, solution, form, field, case_name):
    if (
        not isinstance(case_name, str)
        or not case_name.strip()
        or case_name not in field["options"]
    ):
        raise SolutionError(
            "invalid_answers",
            "Выберите актуальный кейс.",
            status=400,
            errors=[
                issue(
                    "case_name",
                    "case_unavailable",
                    "Выбранный кейс больше недоступен. Выберите актуальный кейс.",
                    field["id"],
                )
            ],
        )
    target = applied_field(solution, field)
    answers = list(solution.answers.order_by("pk").values("id", "field_id", "value"))
    applied_answers = (
        solution.submission_snapshot["answers"]
        if solution.status == "submitted"
        else answers
    )
    current = next(
        (a["value"] for a in applied_answers if a["field_id"] == target["id"]), None
    )
    assignments = list(
        SolutionExpertAssignment.objects.filter(solution=solution)
        .order_by("pk")
        .values("id", "expert_id", "expert__user_id", "partner_program_id")
    )
    scores = list(
        SolutionScore.objects.filter(solution=solution)
        .order_by("pk")
        .values("id", "criteria_id", "user_id", "value")
    )
    scopes = list(
        program.expert_case_scopes.order_by("pk").values(
            "id", "expert_id", "all_cases", "case_names"
        )
    )
    protected = {score["user_id"] for score in scores}
    scoped = {scope["expert_id"]: scope for scope in scopes}
    removed = [
        row["id"]
        for row in assignments
        if row["expert__user_id"] not in protected
        and row["expert_id"] in scoped
        and not scoped[row["expert_id"]]["all_cases"]
        and case_name not in scoped[row["expert_id"]]["case_names"]
    ]
    errors = []
    if solution.status != "submitted" and (assignments or scores):
        errors.append(
            issue(
                "case_name",
                "evaluation_started",
                "У решения уже есть данные оценивания.",
                field["id"],
            )
        )
    elif current == case_name:
        errors.append(
            issue("case_name", "case_unchanged", "Выберите другой кейс.", field["id"])
        )
    state = dict(
        program=[program.pk, program.solution_storage_mode, program.is_competitive],
        form=form,
        solution=list(
            ProgramSolution.objects.filter(pk=solution.pk).values(
                "id",
                "captain_id",
                "name",
                "version",
                "status",
                "submitted_at",
                "submission_snapshot",
                "published_at",
            )
        ),
        answers=answers,
        members=list(
            ProgramSolutionMember.objects.filter(solution=solution)
            .order_by("pk")
            .values("id", "user_id", "role", "specialization")
        ),
        assignments=assignments,
        scores=scores,
        scopes=scopes,
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
            case_field_id=target["id"],
            current_case=current if isinstance(current, str) else None,
            case_name=case_name,
            solution_version=solution.version,
            errors=errors,
            can_apply=not errors,
            is_submitted=solution.status == "submitted",
            removed_assignments_count=len(removed),
            score_count=len(scores),
        ),
        digest,
        removed,
    )


def proof_context(program, solution, actor, case_name):
    return dict(actor=actor.pk, program=program.pk, solution=solution.pk, case=case_name)


@transaction.atomic
def preview(program_id, solution_id, actor, data):
    program, solution, form, field = context(program_id, solution_id, actor)
    result, state, _ = inspect(program, solution, form, field, data["case_name"])
    result["preview_token"] = (
        signing.dumps(
            {
                **proof_context(program, solution, actor, data["case_name"]),
                "state": state,
            },
            salt=SALT,
            compress=True,
        )
        if result["can_apply"]
        else None
    )
    return result


@transaction.atomic
def apply(program_id, solution_id, actor, data):
    program, solution, form, field = context(program_id, solution_id, actor)
    try:
        proof = signing.loads(data["preview_token"], salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as error:
        raise conflict() from error
    expected = proof_context(program, solution, actor, data["case_name"])
    if not isinstance(proof, dict) or any(proof.get(k) != v for k, v in expected.items()):
        raise conflict()
    result, state, removed = inspect(program, solution, form, field, data["case_name"])
    if proof.get("state") != state or not result["can_apply"]:
        raise conflict(result["errors"])
    before_version = solution.version
    before_snapshot = copy.deepcopy(solution.submission_snapshot)
    if solution.status == "submitted":
        target = applied_field(solution, field)
        after = copy.deepcopy(before_snapshot)
        if not any(item["id"] == target["id"] for item in after["form"]["fields"]):
            old_case_ids = {
                item["id"]
                for item in after["form"]["fields"]
                if item["purpose"] == "case"
            }
            if old_case_ids:
                after["form"]["fields"] = [
                    copy.deepcopy(target) if item["id"] in old_case_ids else item
                    for item in after["form"]["fields"]
                ]
                after["answers"] = [
                    item
                    for item in after["answers"]
                    if item["field_id"] not in old_case_ids
                ]
            else:
                after["form"]["fields"].append(copy.deepcopy(target))
            after["form"]["revision"] = hashlib.sha256(
                json.dumps(
                    dict(
                        template=after["form"]["template"], fields=after["form"]["fields"]
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        answer = next(
            (item for item in after["answers"] if item["field_id"] == target["id"]), None
        )
        if answer is None:
            after["answers"].append(dict(field_id=target["id"], value=data["case_name"]))
        else:
            answer["value"] = data["case_name"]
        # Only this confirmed manager writer bypasses ordinary frozen model writes.
        saved = solution.answers.filter(field_id=target["id"])
        if saved.exists():
            saved.update(value=data["case_name"])
        else:
            ProgramSolutionAnswer.objects.bulk_create(
                [
                    ProgramSolutionAnswer(
                        solution=solution, field_id=target["id"], value=data["case_name"]
                    )
                ]
            )
        solution.submission_snapshot = after
        solution.version += 1
        solution.updated_at = timezone.now()
        ProgramSolution.objects.filter(pk=solution.pk).update(
            submission_snapshot=after,
            version=solution.version,
            updated_at=solution.updated_at,
        )
    else:
        ProgramSolutionAnswer.objects.update_or_create(
            solution=solution, field_id=field["id"], defaults={"value": data["case_name"]}
        )
        advance_version(solution)
    SolutionExpertAssignment.objects.filter(pk__in=removed).delete()
    SolutionAdministrativeChange.objects.create(
        solution=solution,
        actor=actor,
        actor_name=f"{actor.first_name} {actor.last_name}".strip(),
        action="change_case",
        before_version=before_version,
        after_version=solution.version,
        case_field_id=result["case_field_id"],
        previous_case=result["current_case"],
        case_name=data["case_name"],
        removed_assignment_ids=removed,
        score_count=result["score_count"],
        was_submitted=solution.status == "submitted",
        before_snapshot=before_snapshot,
        after_snapshot=copy.deepcopy(solution.submission_snapshot),
    )
    logger.info(
        "Program solution case change program=%s actor=%s solution=%s",
        program.pk,
        actor.pk,
        solution.pk,
    )
    return mutation_receipt(solution)
