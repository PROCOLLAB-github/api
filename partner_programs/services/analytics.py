from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import TruncDate, Trim
from django.utils import timezone

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from projects.models import Collaborator
from project_rates.models import ProjectExpertAssignment, ProjectScore

ACTIVITY_DAYS = 30


def _get_participant_metrics(program_id: int) -> dict[str, int]:
    leader_exists = Exists(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            project__leader_id=OuterRef("user_id"),
        )
    )
    submitted_leader_exists = Exists(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            project__leader_id=OuterRef("user_id"),
            submitted=True,
        )
    )
    collaborator_exists = Exists(
        Collaborator.objects.filter(
            user_id=OuterRef("user_id"),
            project__program_links__partner_program_id=program_id,
        )
    )
    profiles = PartnerProgramUserProfile.objects.filter(
        partner_program_id=program_id
    ).annotate(
        is_project_leader=leader_exists,
        is_submitted_project_leader=submitted_leader_exists,
        is_project_collaborator=collaborator_exists,
    )
    participant_filter = Q(user_id__isnull=False)
    team_filter = Q(is_project_leader=True) | Q(is_project_collaborator=True)

    return profiles.aggregate(
        registrations=Count("id"),
        unique_participants=Count(
            "user_id",
            filter=participant_filter,
            distinct=True,
        ),
        with_team=Count(
            "user_id",
            filter=participant_filter & team_filter,
            distinct=True,
        ),
        without_team=Count(
            "user_id",
            filter=(
                participant_filter
                & Q(is_project_leader=False)
                & Q(is_project_collaborator=False)
            ),
            distinct=True,
        ),
        project_creators=Count(
            "user_id",
            filter=participant_filter & Q(is_project_leader=True),
            distinct=True,
        ),
        submitted_project_creators=Count(
            "user_id",
            filter=participant_filter & Q(is_submitted_project_leader=True),
            distinct=True,
        ),
    )


def _get_regions(program_id: int) -> list[dict]:
    return list(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            project__region__isnull=False,
        )
        .annotate(name=Trim("project__region"))
        .exclude(name="")
        .values("name")
        .annotate(count=Count("project_id", distinct=True))
        .order_by("-count", "name")
    )


def _get_solution_metrics(program, assignments_by_project: dict) -> dict[str, int]:
    program_id = program.id
    project_rows = (
        PartnerProgramProject.objects.filter(partner_program_id=program_id)
        .annotate(
            rated_experts=Count(
                "project__scores__user_id",
                filter=Q(
                    project__scores__criteria__partner_program_id=program_id,
                ),
                distinct=True,
            )
        )
        .values_list("project_id", "submitted", "rated_experts")
    )

    metrics = {
        "created": 0,
        "not_submitted": 0,
        "submitted": 0,
        "awaiting_evaluation": 0,
        "partially_evaluated": 0,
        "evaluated": 0,
    }
    for project_id, submitted, rated_experts in project_rows:
        metrics["created"] += 1
        if not submitted:
            metrics["not_submitted"] += 1
            continue

        metrics["submitted"] += 1
        if not program.is_distributed_evaluation:
            status = "evaluated" if rated_experts > 0 else "awaiting_evaluation"
            metrics[status] += 1
            continue

        project_assignments = assignments_by_project.get(
            project_id,
            {"total": 0, "evaluated": 0},
        )
        assigned = project_assignments["total"]
        evaluated_assignments = project_assignments["evaluated"]
        if assigned == 0 or evaluated_assignments == 0:
            metrics["awaiting_evaluation"] += 1
        elif evaluated_assignments < assigned:
            metrics["partially_evaluated"] += 1
        else:
            metrics["evaluated"] += 1

    return metrics


def _get_assignment_metrics(program_id: int) -> tuple[dict[str, int], dict]:
    score_exists = Exists(
        ProjectScore.objects.filter(
            project_id=OuterRef("project_id"),
            user_id=OuterRef("expert__user_id"),
            criteria__partner_program_id=program_id,
        )
    )
    assignment_rows = (
        ProjectExpertAssignment.objects.filter(partner_program_id=program_id)
        .annotate(has_score=score_exists)
        .values_list("project_id", "has_score")
    )
    metrics = {"total": 0, "pending": 0, "evaluated": 0}
    by_project = defaultdict(lambda: {"total": 0, "evaluated": 0})
    for project_id, has_score in assignment_rows:
        metrics["total"] += 1
        metrics["evaluated" if has_score else "pending"] += 1
        by_project[project_id]["total"] += 1
        if has_score:
            by_project[project_id]["evaluated"] += 1
    return metrics, dict(by_project)


def _get_activity(program_id: int) -> list[dict]:
    today = timezone.localdate()
    start_date = today - timedelta(days=ACTIVITY_DAYS - 1)

    registrations = dict(
        PartnerProgramUserProfile.objects.filter(
            partner_program_id=program_id,
            datetime_created__date__gte=start_date,
            datetime_created__date__lte=today,
        )
        .annotate(activity_date=TruncDate("datetime_created"))
        .values("activity_date")
        .annotate(total=Count("id"))
        .values_list("activity_date", "total")
    )
    submissions = dict(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            submitted=True,
            datetime_submitted__date__gte=start_date,
            datetime_submitted__date__lte=today,
        )
        .annotate(activity_date=TruncDate("datetime_submitted"))
        .values("activity_date")
        .annotate(total=Count("id"))
        .values_list("activity_date", "total")
    )

    return [
        {
            "date": activity_date,
            "registrations": registrations.get(activity_date, 0),
            "submitted_solutions": submissions.get(activity_date, 0),
        }
        for activity_date in (
            start_date + timedelta(days=offset) for offset in range(ACTIVITY_DAYS)
        )
    ]


def build_program_manager_analytics(program) -> dict:
    program_id = program.id
    participants = _get_participant_metrics(program_id)
    regions = _get_regions(program_id)
    assignments, assignments_by_project = _get_assignment_metrics(program_id)
    solutions = _get_solution_metrics(program, assignments_by_project)

    projects_awaiting_evaluation = (
        solutions["awaiting_evaluation"] + solutions["partially_evaluated"]
    )

    return {
        "summary": {
            "participants": {"total": participants["unique_participants"]},
            "projects": {"total": solutions["created"]},
            "experts": {"total": program.experts.count()},
            "regions": {"total": len(regions), "items": regions},
        },
        "participant_funnel": {
            "registrations": participants["registrations"],
            "unique_participants": participants["unique_participants"],
            "with_team": participants["with_team"],
            "project_creators": participants["project_creators"],
            "submitted_project_creators": participants["submitted_project_creators"],
        },
        "solution_funnel": {
            "created": solutions["created"],
            "not_submitted": solutions["not_submitted"],
            "submitted": solutions["submitted"],
            "evaluated": solutions["evaluated"],
        },
        "evaluation_status": {
            "mode": ("distributed" if program.is_distributed_evaluation else "open"),
            "max_evaluations_per_project": program.max_project_rates,
            "assignments": {
                "total": assignments["total"],
                "pending": assignments["pending"],
                "evaluated": assignments["evaluated"],
            },
            "projects": {
                "submitted": solutions["submitted"],
                "awaiting_evaluation": solutions["awaiting_evaluation"],
                "partially_evaluated": solutions["partially_evaluated"],
                "evaluated": solutions["evaluated"],
            },
        },
        "attention": {
            "participants_without_team": participants["without_team"],
            "projects_awaiting_evaluation": projects_awaiting_evaluation,
        },
        "activity": _get_activity(program_id),
    }
