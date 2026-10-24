"""Предпросмотр и применение назначений без подстановки solution_id в Project API."""

import hashlib
from collections import Counter, defaultdict

from django.core import signing
from django.db import transaction

from partner_programs.services.case_fields import get_program_case_field
from partner_programs.services.management import person_name
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_forms import require_manager
from partner_programs.solution_team import program_for
from project_rates.allocation_alternatives import alternative_pairs
from project_rates.evaluation_math import complete_values
from project_rates.models import Criteria
from project_rates.solution_assignments import check_revision, revision, enable_workspace
from project_rates.solution_evaluation import snapshot_case, snapshot_name, team_user_ids
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.workspace import eligible, target

SALT = "solution-expert-allocation"


def require_mode(program):
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )


def assignment_snapshot(program, *, include_historical=True):
    pairs = set(
        program.solution_expert_assignments.values_list("solution_id", "expert_id")
    )
    members = dict(program.experts.values_list("user_id", "pk"))
    values = defaultdict(dict)
    for solution_id, user_id, criterion_id, value in SolutionScore.objects.filter(
        criteria__partner_program=program, solution__program=program
    ).values_list("solution_id", "user_id", "criteria_id", "value"):
        if user_id in members:
            pair = (solution_id, members[user_id])
            values[pair][criterion_id] = value
            # Предпросмотр учитывает те же исторические назначения, что явный opt-in.
            if include_historical and program.required_evaluators is None:
                pairs.add(pair)
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    return [
        dict(
            solution_id=sid,
            expert_id=eid,
            is_completed=complete_values(criteria, values[(sid, eid)]),
        )
        for sid, eid in sorted(pairs)
    ]


def load_plan(token, program):
    try:
        plan = signing.loads(token, salt=SALT, max_age=900)
    except signing.BadSignature:
        raise SolutionError(
            "stale_plan", "Предпросмотр устарел. Рассчитайте распределение заново."
        )
    if plan.get("program_id") != program.pk:
        raise SolutionError(
            "invalid_plan", "План принадлежит другой программе.", status=400
        )
    check_revision(program, plan["revision"])
    return plan


def allocation(program, data):
    require_mode(program)
    check_revision(program, data["revision"])
    all_experts = list(
        program.experts.filter(user__is_active=True).select_related("user").order_by("pk")
    )
    selected = set(data["expert_ids"])
    if (not selected and "case_pools" not in data) or selected - {
        e.pk for e in all_experts
    }:
        raise SolutionError(
            "invalid_assignments",
            "Выберите активных экспертов этой программы.",
            status=400,
        )
    scopes = {scope.expert_id: scope for scope in program.expert_case_scopes.all()}
    field = get_program_case_field(program)
    cases = field.get_options_list() if field else []
    pools = None
    if "case_pools" in data:
        pools = {}
        for pool in data["case_pools"]:
            name, members = pool["case_name"], set(pool["expert_ids"])
            if name in pools or (name is not None and name not in cases):
                raise SolutionError(
                    "invalid_assignments",
                    "Проверьте список кейсов распределения.",
                    status=400,
                )
            if members - selected or any(
                not eligible(scopes.get(eid), name) for eid in members
            ):
                raise SolutionError(
                    "invalid_assignments",
                    "Выберите подходящих экспертов для каждого кейса.",
                    status=400,
                )
            pools[name] = members
    experts = [expert for expert in all_experts if expert.pk in selected]
    solutions = list(program.solutions.filter(status="submitted").order_by("pk"))
    if "solution_ids" in data:
        selected_solutions = set(data["solution_ids"])
        if selected_solutions - {row.pk for row in solutions}:
            raise SolutionError(
                "invalid_assignments",
                "Выберите сданные решения этой программы.",
                status=400,
            )
        solutions = [row for row in solutions if row.pk in selected_solutions]
    assignments = assignment_snapshot(program)
    present = {(row["solution_id"], row["expert_id"]) for row in assignments}
    counts = Counter(row["solution_id"] for row in assignments)
    before = Counter(row["expert_id"] for row in assignments if not row["is_completed"])
    remaining = before.copy()
    assigned_before = Counter(row["expert_id"] for row in assignments)
    overrides, solution_ids = {}, {row.pk for row in solutions}
    for row in data.get("assignment_overrides", []):
        sid, ids = row["solution_id"], row["expert_ids"]
        if sid not in solution_ids or sid in overrides or len(set(ids)) != len(ids):
            raise SolutionError(
                "invalid_assignments",
                "Проверьте решения и экспертов в предпросмотре.",
                status=400,
            )
        overrides[sid] = set(ids)
    additions, shortages, candidate_ids = [], [], {}
    seed = data.get("seed")
    for solution in solutions:
        sid, case_name, own = (
            solution.pk,
            snapshot_case(solution),
            team_user_ids(solution),
        )
        needed = max(0, target(program) - counts[sid])
        candidates = [
            expert
            for expert in experts
            if (sid, expert.pk) not in present
            and expert.user_id not in own
            and eligible(scopes.get(expert.pk), case_name)
            and (pools is None or expert.pk in pools.get(case_name, set()))
        ]
        candidates.sort(
            key=lambda expert: (
                remaining[expert.pk],
                expert.pk
                if seed is None
                else hashlib.sha256(f"{seed}:{sid}:{expert.pk}".encode()).digest(),
            )
        )
        candidate_ids[sid] = {expert.pk for expert in candidates}
        if sid in overrides:
            chosen = overrides[sid]
            if chosen - candidate_ids[sid] or len(chosen) > needed:
                raise SolutionError(
                    "invalid_assignments",
                    "Выберите доступных экспертов в пределах числа оценок решения.",
                    status=400,
                )
            proposed = [expert for expert in candidates if expert.pk in chosen]
        else:
            proposed = candidates[:needed]
        for expert in proposed:
            additions.append(
                dict(
                    solution_id=sid,
                    solution_name=snapshot_name(solution),
                    expert_id=expert.pk,
                    expert_name=person_name(expert.user),
                    case_name=case_name,
                )
            )
            remaining[expert.pk] += 1
        if len(proposed) < needed:
            shortages.append(
                dict(
                    solution_id=sid,
                    solution_name=snapshot_name(solution),
                    missing=needed - len(proposed),
                    case_name=case_name,
                )
            )
    if "previous_plan_token" in data:
        if overrides:
            raise SolutionError(
                "invalid_assignments",
                "Обновите предпросмотр после изменения состава.",
                status=400,
            )
        previous = load_plan(data["previous_plan_token"], program)
        previous_pairs = {
            (row["solution_id"], row["expert_id"]) for row in previous["additions"]
        }
        grouped = defaultdict(set)
        for sid, eid in previous_pairs:
            grouped[sid].add(eid)
        if (
            set(grouped) - set(candidate_ids)
            or previous["has_shortages"]
            or any(
                grouped[row.pk] - candidate_ids[row.pk]
                or len(grouped[row.pk]) != max(0, target(program) - counts[row.pk])
                for row in solutions
            )
        ):
            raise SolutionError(
                "invalid_assignments",
                "Параметры распределения изменились. Обновите предпросмотр.",
                status=400,
            )
        load = before + Counter(eid for _, eid in previous_pairs)
        different = alternative_pairs(previous_pairs, candidate_ids, load, seed or 0)
        if different is None:
            raise SolutionError(
                "no_alternative", "Другого сбалансированного варианта нет."
            )
        by_solution, by_expert = {row.pk: row for row in solutions}, {
            row.pk: row for row in experts
        }
        additions = [
            dict(
                solution_id=sid,
                solution_name=snapshot_name(by_solution[sid]),
                expert_id=eid,
                expert_name=person_name(by_expert[eid].user),
                case_name=snapshot_case(by_solution[sid]),
            )
            for sid, eid in sorted(different)
        ]
        shortages = []
    pairs = {(row["solution_id"], row["expert_id"]) for row in additions}
    added = Counter(eid for _, eid in pairs)
    remaining = before + added
    rev = revision(program)
    token = signing.dumps(
        dict(
            program_id=program.pk,
            revision=rev,
            has_shortages=bool(shortages),
            additions=[
                dict(solution_id=row["solution_id"], expert_id=row["expert_id"])
                for row in additions
            ],
        ),
        salt=SALT,
        compress=True,
    )
    return dict(
        revision=rev,
        plan_token=token,
        assignments=additions,
        shortages=shortages,
        can_reroll=not shortages
        and alternative_pairs(pairs, candidate_ids, remaining) is not None,
        load=[
            dict(
                expert_id=e.pk,
                name=person_name(e.user),
                before=before[e.pk],
                after=remaining[e.pk],
                assigned_before=assigned_before[e.pk],
                assigned_after=assigned_before[e.pk] + added[e.pk],
            )
            for e in all_experts
        ],
    )


@transaction.atomic
def preview_allocation(*, program_id, actor, data):
    program = program_for(program_id, lock=True)
    require_manager(program, actor)
    return allocation(program, data)


@transaction.atomic
def apply_allocation(*, program_id, actor, plan_token):
    program = program_for(program_id, lock=True)
    require_manager(program, actor)
    require_mode(program)
    plan = load_plan(plan_token, program)
    if plan["has_shortages"]:
        raise SolutionError(
            "expert_shortage", "Не хватает экспертов. Измените параметры распределения."
        )
    enable_workspace(program)
    existing = set(
        program.solution_expert_assignments.values_list("solution_id", "expert_id")
    )
    new_pairs = {
        (row["solution_id"], row["expert_id"]) for row in plan["additions"]
    } - existing
    counts = Counter(sid for sid, _ in existing)
    added = Counter(sid for sid, _ in new_pairs)
    if any(counts[sid] + number > target(program) for sid, number in added.items()):
        raise SolutionError(
            "expert_limit_reached", "Достигнут лимит новых назначений экспертов."
        )
    SolutionExpertAssignment.objects.bulk_create(
        [
            SolutionExpertAssignment(
                partner_program=program, solution_id=sid, expert_id=eid
            )
            for sid, eid in sorted(new_pairs)
        ]
    )
    return dict(program_id=program.pk, revision=revision(program), created=len(new_pairs))


def quota_preview(program, number):
    require_mode(program)
    assignments = assignment_snapshot(program)
    completed = Counter(row["solution_id"] for row in assignments if row["is_completed"])
    counts = Counter(row["solution_id"] for row in assignments)
    ids = set(program.solutions.filter(status="submitted").values_list("pk", flat=True))
    return dict(
        revision=revision(program),
        required_evaluators=number,
        submitted_solutions=len(ids),
        solutions_missing_experts=sum(counts[sid] < number for sid in ids),
        ready_before=sum(completed[sid] >= target(program) for sid in ids),
        ready_after=sum(completed[sid] >= number for sid in ids),
        missing_assignments=sum(max(0, number - counts[sid]) for sid in ids),
        surplus_assignments=sum(max(0, counts[sid] - number) for sid in ids),
    )


@transaction.atomic
def save_quota(*, program_id, actor, revision, required_evaluators):
    program = program_for(program_id, lock=True)
    require_manager(program, actor)
    require_mode(program)
    check_revision(program, revision)
    before = quota_preview(program, required_evaluators)
    enable_workspace(program)
    program.required_evaluators = required_evaluators
    program.save(update_fields=["required_evaluators", "datetime_updated"])
    return {**before, "revision": quota_preview(program, required_evaluators)["revision"]}
