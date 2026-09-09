"""Read-only legacy Project analytics, independent of the Application domain."""

from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.services.project_assignment_analytics import (
    build_assignments,
    build_delayed_experts,
)
from project_rates.models import ProjectScore
from projects.models import Collaborator

ACTIVITY_DAYS = 30


def _participant_metrics(program_id):
    links = PartnerProgramProject.objects.filter(
        partner_program_id=program_id,
        project__leader_id=OuterRef("user_id"),
    )
    profiles = PartnerProgramUserProfile.objects.filter(
        partner_program_id=program_id
    ).annotate(
        is_leader=Exists(links),
        is_submitted_leader=Exists(links.filter(submitted=True)),
        is_collaborator=Exists(
            Collaborator.objects.filter(
                user_id=OuterRef("user_id"),
                project__program_links__partner_program_id=program_id,
            )
        ),
    )
    participant = Q(user_id__isnull=False)
    return profiles.aggregate(
        registrations=Count("pk"),
        unique_participants=Count("user_id", filter=participant, distinct=True),
        with_team=Count(
            "user_id",
            filter=participant & (Q(is_leader=True) | Q(is_collaborator=True)),
            distinct=True,
        ),
        project_creators=Count(
            "user_id", filter=participant & Q(is_leader=True), distinct=True
        ),
        submitted_project_creators=Count(
            "user_id", filter=participant & Q(is_submitted_leader=True), distinct=True
        ),
    )


def _regions(queryset, *, field, identity):
    # Each identity has one stored value. Merge SQL groups after a Unicode trim,
    # preserving spelling/case and excluding tabs/newlines as well as plain spaces.
    groups = (
        queryset.values(field).annotate(total=Count(identity, distinct=True)).order_by()
    )
    counts = Counter()
    for group in groups:
        name = (group[field] or "").strip()
        if name:
            counts[name] += group["total"]
    items = [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"total": len(items), "items": items}


def _assignment_metrics(assignments):
    """Reuse shared statuses, with no second assignment query or completion rule."""
    metrics = {"total": 0, "pending": 0, "evaluated": 0}
    by_project = defaultdict(lambda: {"total": 0, "evaluated": 0})
    for assignment in assignments:
        project_id = assignment["project"]["id"]
        completed = assignment["status"] == "completed"
        metrics["total"] += 1
        metrics["evaluated" if completed else "pending"] += 1
        by_project[project_id]["total"] += 1
        by_project[project_id]["evaluated"] += int(completed)
    return metrics, by_project


def _solution_metrics(program, assignments):
    rows = (
        PartnerProgramProject.objects.filter(partner_program_id=program.pk)
        .annotate(
            has_score=Exists(
                ProjectScore.objects.filter(
                    project_id=OuterRef("project_id"),
                    criteria__partner_program_id=program.pk,
                )
            )
        )
        .values_list("project_id", "submitted", "has_score")
    )
    metrics = {
        "created": 0,
        "not_submitted": 0,
        "submitted": 0,
        "awaiting_evaluation": 0,
        "partially_evaluated": 0,
        "evaluated": 0,
    }
    for project_id, submitted, has_score in rows:
        metrics["created"] += 1
        if not submitted:
            metrics["not_submitted"] += 1
            continue
        metrics["submitted"] += 1
        if not program.is_distributed_evaluation:
            state = "evaluated" if has_score else "awaiting_evaluation"
        else:
            assigned = assignments.get(project_id, {"total": 0, "evaluated": 0})
            if assigned["evaluated"] == 0:
                state = "awaiting_evaluation"
            elif assigned["evaluated"] < assigned["total"]:
                state = "partially_evaluated"
            else:
                state = "evaluated"
        metrics[state] += 1
    return metrics


def _activity(program_id):
    today = timezone.localdate()
    start = today - timedelta(days=ACTIVITY_DAYS - 1)
    registrations = dict(
        PartnerProgramUserProfile.objects.filter(
            partner_program_id=program_id,
            datetime_created__date__range=(start, today),
        )
        .annotate(day=TruncDate("datetime_created"))
        .values("day")
        .annotate(total=Count("pk"))
        .values_list("day", "total")
    )
    submissions = dict(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            submitted=True,
            datetime_submitted__date__range=(start, today),
        )
        .annotate(day=TruncDate("datetime_submitted"))
        .values("day")
        .annotate(total=Count("pk"))
        .values_list("day", "total")
    )
    return [
        {
            "date": day,
            "registrations": registrations.get(day, 0),
            "submitted_solutions": submissions.get(day, 0),
        }
        for day in (start + timedelta(days=offset) for offset in range(ACTIVITY_DAYS))
    ]


def build_project_analytics(program) -> dict:
    participants = _participant_metrics(program.pk)
    assignment_details = build_assignments(program.pk)
    assignments, by_project = _assignment_metrics(assignment_details)
    solutions = _solution_metrics(program, by_project)
    return {
        "summary": {
            "participants": {"total": participants["unique_participants"]},
            "projects": {"total": solutions["created"]},
            "experts": {"total": program.experts.count()},
            "regions": _regions(
                PartnerProgramProject.objects.filter(partner_program_id=program.pk),
                field="project__region",
                identity="project_id",
            ),
            "participant_regions": _regions(
                PartnerProgramUserProfile.objects.filter(
                    partner_program_id=program.pk, user_id__isnull=False
                ),
                field="user__city",
                identity="user_id",
            ),
        },
        "participant_funnel": participants,
        "solution_funnel": {
            key: solutions[key]
            for key in ("created", "not_submitted", "submitted", "evaluated")
        },
        "evaluation_status": {
            "mode": "distributed" if program.is_distributed_evaluation else "open",
            "max_evaluations_per_project": program.max_project_rates,
            "assignments": assignments,
            "projects": {
                key: solutions[key]
                for key in (
                    "submitted",
                    "awaiting_evaluation",
                    "partially_evaluated",
                    "evaluated",
                )
            },
        },
        "attention": {
            "participants_without_team": (
                participants["unique_participants"] - participants["with_team"]
            ),
            "projects_awaiting_evaluation": (
                solutions["awaiting_evaluation"] + solutions["partially_evaluated"]
            ),
            "delayed_experts": (
                build_delayed_experts(assignment_details)
                if program.is_distributed_evaluation
                else {"total": 0, "items": []}
            ),
        },
        "activity": _activity(program.pk),
    }
