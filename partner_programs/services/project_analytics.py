"""Read-only legacy Project analytics, independent of the Application domain."""

from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import (
    Case,
    CharField,
    Count,
    Exists,
    F,
    IntegerField,
    Min,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.services.project_assignment_analytics import (
    annotated_assignment_queryset,
    build_assignments,
    build_delayed_experts,
)
from partner_programs.services.project_case_analytics import (
    build_project_case_analytics,
)
from project_rates.models import ProjectScore
from projects.models import Collaborator

ACTIVITY_DAYS = 30


def _participant_profiles(program_id):
    links = PartnerProgramProject.objects.filter(
        partner_program_id=program_id,
        project__leader_id=OuterRef("user_id"),
    )
    return PartnerProgramUserProfile.objects.filter(
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


def _without_team_filter():
    return Q(user_id__isnull=False, is_leader=False, is_collaborator=False)


def participants_without_team_rows(program_id):
    return (
        _participant_profiles(program_id)
        .filter(_without_team_filter())
        .order_by()
        .values(
            "user_id",
            "user__first_name",
            "user__last_name",
            "user__avatar",
            "user__city",
        )
        .annotate(registered_at=Min("datetime_created"))
    )


def _participant_metrics(program_id):
    profiles = _participant_profiles(program_id)
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


def _annotated_solution_rows(program):
    """SQL classification for paginated attention, using shared completion."""
    rows = PartnerProgramProject.objects.filter(partner_program_id=program.pk)
    if program.is_distributed_evaluation:
        assignment_totals = (
            annotated_assignment_queryset(program.pk)
            .filter(project_id=OuterRef("project_id"))
            .order_by()
            .values("project_id")
            .annotate(
                total=Count("pk"),
                completed=Count("pk", filter=Q(is_completed=True)),
            )
        )
        rows = rows.annotate(
            assignments_total=Coalesce(
                Subquery(assignment_totals.values("total")[:1]), 0
            ),
            assignments_completed=Coalesce(
                Subquery(assignment_totals.values("completed")[:1]), 0
            ),
        )
        evaluated_status = Case(
            When(
                Q(assignments_total=0) | Q(assignments_completed=0),
                then=Value("awaiting_evaluation"),
            ),
            When(
                assignments_completed__lt=F("assignments_total"),
                then=Value("partially_evaluated"),
            ),
            default=Value("evaluated"),
            output_field=CharField(),
        )
        waiting_reason = Case(
            When(assignments_total=0, then=Value("no_assignments")),
            When(
                assignments_completed=0,
                then=Value("no_completed_evaluations"),
            ),
            default=Value("partially_evaluated"),
            output_field=CharField(),
        )
    else:
        rows = rows.annotate(
            assignments_total=Value(None, output_field=IntegerField()),
            assignments_completed=Value(None, output_field=IntegerField()),
            has_program_score=Exists(
                ProjectScore.objects.filter(
                    project_id=OuterRef("project_id"),
                    criteria__partner_program_id=program.pk,
                )
            ),
        )
        evaluated_status = Case(
            When(has_program_score=True, then=Value("evaluated")),
            default=Value("awaiting_evaluation"),
            output_field=CharField(),
        )
        waiting_reason = Value("awaiting_first_evaluation", output_field=CharField())
    return rows.annotate(
        status=Case(
            When(submitted=False, then=Value("not_submitted")),
            default=evaluated_status,
            output_field=CharField(),
        ),
        reason=waiting_reason,
    )


def projects_awaiting_evaluation_rows(program):
    return (
        _annotated_solution_rows(program)
        .filter(status__in=("awaiting_evaluation", "partially_evaluated"))
        .select_related("project", "project__leader")
        .only(
            "id",
            "project_id",
            "datetime_submitted",
            "project__name",
            "project__leader_id",
            "project__leader__id",
            "project__leader__first_name",
            "project__leader__last_name",
            "project__leader__avatar",
        )
    )


def projects_not_submitted_rows(program):
    rows = PartnerProgramProject.objects.filter(
        partner_program_id=program.pk, submitted=False
    )
    if not program.is_competitive:
        return rows.none()
    return rows.select_related("project", "project__leader").only(
        "id",
        "project_id",
        "datetime_created",
        "project__name",
        "project__leader_id",
        "project__leader__id",
        "project__leader__first_name",
        "project__leader__last_name",
        "project__leader__avatar",
    )


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
    cases = build_project_case_analytics(program)
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
            "projects_not_submitted": {
                "applicable": program.is_competitive,
                "total": solutions["not_submitted"] if program.is_competitive else 0,
            },
            "delayed_experts": (
                build_delayed_experts(assignment_details)
                if program.is_distributed_evaluation
                else {"total": 0, "items": []}
            ),
        },
        "activity": _activity(program.pk),
        "cases": cases,
    }
