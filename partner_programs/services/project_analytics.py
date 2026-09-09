"""Read-only legacy Project analytics, independent of the Application domain."""

from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
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


def _assignment_metrics(program_id):
    """DEV #724 completion: submitted link and scores for all current criteria."""
    criteria = (
        Criteria.objects.filter(partner_program_id=program_id)
        .order_by()
        .values("partner_program_id")
        .annotate(total=Count("pk"))
    )
    scores = (
        ProjectScore.objects.filter(
            criteria__partner_program_id=program_id,
            project_id=OuterRef("project_id"),
            user_id=OuterRef("expert__user_id"),
        )
        .order_by()
        .values("project_id", "user_id")
        .annotate(total=Count("criteria_id", distinct=True))
    )
    rows = (
        ProjectExpertAssignment.objects.filter(partner_program_id=program_id)
        .annotate(
            criteria_total=Coalesce(Subquery(criteria.values("total")[:1]), 0),
            criteria_scored=Coalesce(Subquery(scores.values("total")[:1]), 0),
            project_submitted=Exists(
                PartnerProgramProject.objects.filter(
                    partner_program_id=program_id,
                    project_id=OuterRef("project_id"),
                    submitted=True,
                )
            ),
        )
        .values_list(
            "project_id", "project_submitted", "criteria_total", "criteria_scored"
        )
    )
    metrics = {"total": 0, "pending": 0, "evaluated": 0}
    by_project = defaultdict(lambda: {"total": 0, "evaluated": 0})
    for project_id, submitted, total, scored in rows:
        completed = submitted and total > 0 and scored >= total
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
    assignments, by_project = _assignment_metrics(program.pk)
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
        },
        "activity": _activity(program.pk),
    }
