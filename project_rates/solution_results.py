"""Результаты решений с прежней математикой; сериализация доступна только через scoped API."""

from collections import defaultdict

from django.utils import timezone

from partner_programs.services.case_fields import get_program_case_field
from partner_programs.services.management import person_name
from partner_programs.solution_errors import SolutionError
from project_rates.evaluation_math import evaluation_totals, assign_places
from project_rates.models import Criteria
from project_rates.solution_evaluation import snapshot_case, snapshot_name
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore


def results_data(program, query, *, solution_id=None):
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    field = get_program_case_field(program)
    options = field.get_options_list() if field else []
    if query["case_scope"] == "selected" and query.get("case_name") not in options:
        raise SolutionError("invalid_filter", "Выберите существующий кейс.", status=400)
    solutions = program.solutions.filter(status="submitted").order_by("pk")
    if solution_id is not None:
        solutions = solutions.filter(pk=solution_id)
    solutions = list(solutions)
    ids = [row.pk for row in solutions]
    values, people = defaultdict(dict), defaultdict(dict)
    for score in SolutionScore.objects.filter(
        criteria__partner_program=program, solution_id__in=ids
    ).select_related("user"):
        values[(score.solution_id, score.user_id)][score.criteria_id] = score.value
        people[score.solution_id][score.user_id] = score.user
    for assignment in SolutionExpertAssignment.objects.filter(
        partner_program=program, solution_id__in=ids
    ).select_related("expert__user"):
        people[assignment.solution_id][assignment.expert.user_id] = assignment.expert.user
    required = program.required_evaluators or program.max_project_rates or 1
    buckets = {name: [] for name in [*options, None]}
    for solution in solutions:
        totals = evaluation_totals(
            criteria,
            {user_id: values[(solution.pk, user_id)] for user_id in people[solution.pk]},
        )
        experts = [
            dict(
                user_id=user_id,
                name=person_name(user),
                email=user.email,
                avatar=user.avatar or None,
                **totals["evaluations"][user_id],
                values=[
                    dict(
                        criterion_id=c.pk, value=values[(solution.pk, user_id)].get(c.pk)
                    )
                    for c in criteria
                ],
            )
            for user_id, user in sorted(people[solution.pk].items())
        ]
        complete = totals["completed"] >= required
        case_name = snapshot_case(solution)
        buckets.setdefault(case_name, []).append(
            dict(
                application=dict(
                    kind="solution",
                    program_id=program.pk,
                    solution_id=solution.pk,
                    name=snapshot_name(solution),
                ),
                solution_id=solution.pk,
                name=snapshot_name(solution),
                case_name=case_name,
                completed=totals["completed"],
                required=required,
                evaluation_complete=complete,
                ready=complete and totals["score"] is not None,
                score=totals["score"],
                place=None,
                averages=totals["averages"],
                experts=experts,
            )
        )
    groups = []
    for case_name, rows in buckets.items():
        if solution_id is None:
            assign_places(rows, "solution_id")
        if query["scope"] != "all":
            if query["case_scope"] == "selected" and case_name != query.get("case_name"):
                continue
            if query["case_scope"] == "without_case" and case_name is not None:
                continue
            rows = [row for row in rows if query["search"].lower() in row["name"].lower()]
            if query.get("status", "all") != "all":
                rows = [
                    row
                    for row in rows
                    if row["evaluation_complete"] == (query["status"] == "complete")
                ]
        sign = -1 if query["order"] == "desc" else 1
        rows.sort(
            key=lambda row: (
                not row["evaluation_complete"],
                row["score"] is None,
                sign * (row["score"] or 0),
                row["name"].lower(),
                row["solution_id"],
            )
        )
        if rows:
            groups.append(dict(case_name=case_name, solutions=rows))
    base = evaluation_totals(criteria, {})
    return dict(
        program_id=program.pk,
        program_name=program.name,
        generated_at=timezone.now(),
        required_evaluators=required,
        maximum=base["maximum"],
        has_numeric_criteria=base["has_numeric_criteria"],
        case_options=options,
        groups=groups,
        criteria=[
            dict(
                id=c.pk,
                name=c.name,
                description=c.description,
                type=c.type,
                min_value=c.min_value,
                max_value=c.max_value,
            )
            for c in criteria
        ],
    )
