"""Confirmed organizer case changes without changing submitted materials."""

import hashlib
import json
import logging

from django.core import signing
from django.db import transaction
from django.http import Http404

from partner_programs.permissions import can_manage_program
from partner_programs.solution_api import mutation_receipt
from partner_programs.solution_errors import MAX_ID, SolutionError, issue
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
)
from partner_programs.solution_schema import form_data
from partner_programs.solution_team import (
    advance_version,
    program_for,
    require_mutable,
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
    answers = list(solution.answers.order_by("pk").values("id", "field_id", "value"))
    current = next((a["value"] for a in answers if a["field_id"] == field["id"]), None)
    assignments = list(
        SolutionExpertAssignment.objects.filter(solution=solution)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    scores = list(
        SolutionScore.objects.filter(solution=solution)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    errors = []
    if solution.status == "submitted":
        errors.append(
            issue(
                "case_name",
                "team_frozen",
                "Данные сданного решения зафиксированы.",
                field["id"],
            )
        )
    elif assignments or scores:
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
            case_field_id=field["id"],
            current_case=current if isinstance(current, str) else None,
            case_name=case_name,
            solution_version=solution.version,
            errors=errors,
            can_apply=not errors,
        ),
        digest,
    )


def proof_context(program, solution, actor, case_name):
    return dict(actor=actor.pk, program=program.pk, solution=solution.pk, case=case_name)


@transaction.atomic
def preview(program_id, solution_id, actor, data):
    program, solution, form, field = context(program_id, solution_id, actor)
    result, state = inspect(program, solution, form, field, data["case_name"])
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
    require_mutable(solution)
    try:
        proof = signing.loads(data["preview_token"], salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as error:
        raise conflict() from error
    expected = proof_context(program, solution, actor, data["case_name"])
    if not isinstance(proof, dict) or any(proof.get(k) != v for k, v in expected.items()):
        raise conflict()
    result, state = inspect(program, solution, form, field, data["case_name"])
    if proof.get("state") != state or not result["can_apply"]:
        raise conflict(result["errors"])
    ProgramSolutionAnswer.objects.update_or_create(
        solution=solution, field_id=field["id"], defaults={"value": data["case_name"]}
    )
    advance_version(solution)
    logger.info(
        "Program solution case change program=%s actor=%s solution=%s",
        program.pk,
        actor.pk,
        solution.pk,
    )
    return mutation_receipt(solution)
