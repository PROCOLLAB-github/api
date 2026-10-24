"""Назначения решения: общая блокировка программы и ревизия реального состояния."""

import hashlib
import json
from collections import Counter

from django.db import transaction
from django.http import Http404

from partner_programs.solution_errors import SolutionError
from partner_programs.solution_forms import require_manager
from partner_programs.solution_schema import form_data
from partner_programs.solution_team import program_for
from project_rates.criteria_policy import revision as criteria_revision
from project_rates.models import Criteria
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.solution_evaluation import (
    snapshot_case,
    snapshot_name,
    team_user_ids,
    metrics,
    complete_values,
)
from project_rates.workspace import eligible, target


def revision(program):
    payload = [
        program.pk,
        program.required_evaluators,
        program.max_project_rates,
        program.is_distributed_evaluation,
        list(
            program.solutions.order_by("pk").values_list(
                "pk", "version", "status", "captain_id", "name"
            )
        ),
        list(
            program.experts.order_by("pk").values_list("pk", "user_id", "user__is_active")
        ),
        list(
            program.solution_expert_assignments.order_by("pk").values_list(
                "pk", "solution_id", "expert_id"
            )
        ),
        list(
            SolutionScore.objects.filter(criteria__partner_program=program)
            .order_by("pk")
            .values_list("pk", "solution_id", "user_id", "criteria_id", "value")
        ),
        list(
            program.expert_case_scopes.order_by("expert_id").values_list(
                "expert_id", "all_cases", "case_names"
            )
        ),
        list(
            program.fields.filter(name="case")
            .order_by("pk")
            .values_list("pk", "options", "solution_options")
        ),
        criteria_revision(program),
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def check_revision(program, expected):
    actual = revision(program)
    if expected != actual:
        raise SolutionError(
            "stale_assignments",
            "Данные изменились. Обновите список назначений.",
            meta={"current_assignment_revision": actual},
        )


def expert_for(program, expert_id):
    if not 0 < expert_id <= 2**53 - 1:
        raise Http404
    expert = (
        program.experts.filter(pk=expert_id, user__is_active=True)
        .select_related("user")
        .first()
    )
    if expert is None:
        raise Http404
    return expert


def assignment_options(program, expert):
    solutions = list(
        program.solutions.prefetch_related("members", "answers").order_by("pk")
    )
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    states = metrics(program, solutions, expert.user, criteria)
    scope = program.expert_case_scopes.filter(expert=expert).first()
    case_field = next(
        (field for field in form_data(program)["fields"] if field["purpose"] == "case"),
        None,
    )
    rows = []
    for solution in solutions:
        state = states[solution.pk]
        case_name = snapshot_case(
            solution, draft_field_id=case_field["id"] if case_field else None
        )
        rows.append(
            dict(
                solution_id=solution.pk,
                name=snapshot_name(solution),
                case_name=case_name,
                submitted=solution.status == "submitted",
                assigned=state["assigned"] or bool(state["own"]),
                protected=bool(state["own"]),
                is_completed=solution.status == "submitted"
                and complete_values(criteria, state["own"]),
                own_team=expert.user_id in team_user_ids(solution),
                eligible=eligible(scope, case_name),
            )
        )
    return dict(
        program_id=program.pk,
        expert_id=expert.pk,
        revision=revision(program),
        solutions=rows,
    )


def enable_workspace(program):
    """Тот же явный opt-in, включая сохранение назначений за историческими оценками."""
    if program.required_evaluators is not None:
        return
    program.required_evaluators = target(program)
    program.is_distributed_evaluation = True
    program.save(
        update_fields=[
            "required_evaluators",
            "is_distributed_evaluation",
            "datetime_updated",
        ]
    )
    members = dict(program.experts.values_list("user_id", "pk"))
    historical = (
        SolutionScore.objects.filter(
            criteria__partner_program=program, solution__program=program
        )
        .values_list("solution_id", "user_id")
        .distinct()
    )
    SolutionExpertAssignment.objects.bulk_create(
        [
            SolutionExpertAssignment(
                partner_program=program,
                solution_id=solution_id,
                expert_id=members[user_id],
            )
            for solution_id, user_id in historical
            if user_id in members
        ],
        ignore_conflicts=True,
    )


@transaction.atomic
def save_assignments(*, program_id, actor, expert_id, expected_revision, solution_ids):
    program = program_for(program_id, lock=True)
    require_manager(program, actor)
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    check_revision(program, expected_revision)
    expert = expert_for(program, expert_id)
    if len(solution_ids) != len(set(solution_ids)):
        raise SolutionError(
            "invalid_assignments", "Решения не должны повторяться.", status=400
        )
    enable_workspace(program)
    options = {
        row["solution_id"]: row
        for row in assignment_options(program, expert)["solutions"]
    }
    existing = set(
        program.solution_expert_assignments.filter(expert=expert).values_list(
            "solution_id", flat=True
        )
    )
    wanted = set(solution_ids)
    if wanted - options.keys():
        raise SolutionError(
            "invalid_assignments", "Выберите решения этой программы.", status=400
        )
    protected = {pk for pk, row in options.items() if row["protected"]}
    if protected - wanted:
        raise SolutionError(
            "scores_protected", "Нельзя снять назначение с сохраненными оценками."
        )
    for pk in wanted - existing:
        row = options[pk]
        if not row["submitted"] or row["own_team"] or not row["eligible"]:
            raise SolutionError(
                "invalid_assignments",
                "Можно назначить только сданное решение доступного кейса, кроме своей команды.",
                status=400,
            )
    counts = Counter(
        program.solution_expert_assignments.values_list("solution_id", flat=True)
    )
    if any(counts[pk] >= target(program) for pk in wanted - existing):
        raise SolutionError(
            "expert_limit_reached", "Достигнут лимит новых назначений экспертов."
        )
    program.solution_expert_assignments.filter(
        expert=expert, solution_id__in=existing - wanted
    ).delete()
    SolutionExpertAssignment.objects.bulk_create(
        [
            SolutionExpertAssignment(
                partner_program=program, solution_id=pk, expert=expert
            )
            for pk in sorted(wanted - existing)
        ]
    )
    return program, expert
