"""Read-only widget data owned by the solution, without a Project projection."""

from collections import defaultdict

from django.db.models import Count, Q
from rest_framework.exceptions import APIException

from partner_programs.services.analytics import _get_participant_metrics
from partner_programs.services.case_fields import get_program_case_field
from partner_programs.solution_models import ProgramSolution
from project_rates.evaluation_math import complete_values
from project_rates.models import Criteria
from project_rates.solution_evaluation import snapshot_case, snapshot_name
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore


class ParticipantSolutionIntegrityError(APIException):
    status_code = 409
    default_detail = "Связи заявки требуют проверки организатором."
    default_code = "participant_solution_integrity_error"


def criteria_for(program):
    return list(
        Criteria.objects.filter(partner_program=program).only(
            "pk", "type", "min_value", "max_value"
        )
    )


def solution_stage(program, solution):
    """Same participant stages as the current distributed/open analytics."""
    if not program.is_competitive:
        return "not_applicable"
    if solution.status != "submitted":
        return "not_submitted"
    scores = SolutionScore.objects.filter(
        solution=solution, criteria__partner_program=program
    )
    if not program.is_distributed_evaluation:
        return "evaluated" if scores.exists() else "submitted"
    assigned_users = list(
        SolutionExpertAssignment.objects.filter(
            partner_program=program, solution=solution
        ).values_list("expert__user_id", flat=True)
    )
    values = defaultdict(dict)
    for user_id, criterion_id, value in scores.values_list(
        "user_id", "criteria_id", "value"
    ):
        values[user_id][criterion_id] = value
    criteria = criteria_for(program)
    completed = sum(complete_values(criteria, values[user]) for user in assigned_users)
    required = program.required_evaluators or len(assigned_users)
    if assigned_users and completed and completed >= required:
        return "evaluated"
    return "review" if assigned_users or values else "submitted"


def participant_metrics(program, user):
    from partner_programs.services.role_analytics import participant_project_links

    # Read ownership and the row together; no first-match or second unscoped lookup.
    owned = list(
        ProgramSolution.objects.filter(program=program)
        .filter(Q(captain=user) | Q(members__user=user))
        .distinct()
        .prefetch_related("answers")
        .order_by("created_at", "pk")[:2]
    )
    if len(owned) > 1 or participant_project_links(program, user).exists():
        raise ParticipantSolutionIntegrityError()
    result = dict(
        application=None,
        case_provided=False,
        case_name=None,
        stage="none" if program.is_competitive else "not_applicable",
        submission_open=program.is_project_submission_open(),
    )
    if not owned:
        result["case_provided"] = get_program_case_field(program) is not None
        return result
    solution = owned[0]
    result["application"] = dict(
        kind="solution",
        program_id=program.pk,
        solution_id=solution.pk,
        name=snapshot_name(solution),
    )
    if solution.status == "submitted":
        result["case_provided"] = any(
            field["purpose"] == "case"
            for field in (solution.submission_snapshot or {})
            .get("form", {})
            .get("fields", [])
        )
        result["case_name"] = snapshot_case(solution)
    else:
        field = get_program_case_field(program)
        result["case_provided"] = field is not None
        result["case_name"] = snapshot_case(
            solution, draft_field_id=field.pk if field else None
        )
    result["stage"] = solution_stage(program, solution)
    return result


def organizer_metrics(program):
    participants = _get_participant_metrics(program.pk)
    solutions = program.solutions.aggregate(
        created=Count("pk"), submitted=Count("pk", filter=Q(status="submitted"))
    )
    return dict(
        participants=participants["unique_participants"],
        solutions=solutions["created"],
        submitted_solutions=solutions["submitted"] if program.is_competitive else None,
        participants_without_solution=participants["without_team"],
    )


def expert_metrics(program, user):
    mode = "distributed" if program.is_distributed_evaluation else "open"
    if mode == "open" or not program.is_competitive:
        return dict(mode=mode, assigned=None, remaining=None)
    assignments = list(
        SolutionExpertAssignment.objects.filter(
            partner_program=program, expert__user=user, solution__archived_at__isnull=True
        ).values("solution_id", "solution__program_id", "solution__status")
    )
    readable = {
        row["solution_id"]
        for row in assignments
        if row["solution__program_id"] == program.pk
        and row["solution__status"] == "submitted"
    }
    criteria = criteria_for(program)
    values = defaultdict(dict)
    for solution_id, criterion_id, value in SolutionScore.objects.filter(
        solution_id__in=readable, user=user, criteria__partner_program=program
    ).values_list("solution_id", "criteria_id", "value"):
        values[solution_id][criterion_id] = value
    completed = sum(complete_values(criteria, values[pk]) for pk in readable)
    return dict(
        mode=mode, assigned=len(assignments), remaining=len(assignments) - completed
    )


def build_solution_role_widget(program, user, role):
    result = dict(
        program_id=program.pk,
        storage_mode="solution",
        role=role,
        is_competitive=program.is_competitive,
    )
    if role == "organizer":
        result[role] = organizer_metrics(program)
    elif role == "expert":
        result[role] = {
            **expert_metrics(program, user),
            "evaluation_ends": program.datetime_evaluation_ends,
        }
    else:
        result[role] = participant_metrics(program, user)
    return result
