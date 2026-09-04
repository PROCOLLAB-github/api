"""Read-only analytics of real expert assignments; no scoring/lifecycle writes."""

from django.db.models import BooleanField, Count, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from partner_programs.models import PartnerProgramProject
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore


def assignment_rows(program_id):
    """One SELECT with indexed subqueries, not a query per serialized assignment."""
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
    link = PartnerProgramProject.objects.filter(
        partner_program_id=program_id, project_id=OuterRef("project_id")
    ).order_by("pk")
    return (
        ProjectExpertAssignment.objects.filter(partner_program_id=program_id)
        .annotate(
            criteria_total=Coalesce(Subquery(criteria.values("total")[:1]), 0),
            criteria_scored=Coalesce(Subquery(scores.values("total")[:1]), 0),
            project_submitted=Coalesce(
                Subquery(link.values("submitted")[:1]),
                Value(False),
                output_field=BooleanField(),
            ),
            project_submitted_at=Subquery(link.values("datetime_submitted")[:1]),
        )
        .order_by("pk")
        .values(
            "id",
            "expert_id",
            "expert__user_id",
            "expert__user__first_name",
            "expert__user__last_name",
            "expert__user__avatar",
            "project_id",
            "project__name",
            "datetime_created",
            "criteria_total",
            "criteria_scored",
            "project_submitted",
            "project_submitted_at",
        )
    )


def build_assignment(row, *, now):
    total, scored = row["criteria_total"], row["criteria_scored"]
    if not row["project_submitted"]:
        status = "not_ready"
    elif total > 0 and scored >= total:
        status = "completed"
    elif total > 0 and scored > 0:
        status = "in_progress"
    else:
        status = "pending"

    submitted_at = row["project_submitted_at"] if row["project_submitted"] else None
    waiting_since = None
    waiting_seconds = None
    # Missing historical submission timestamps cannot establish an SLA start.
    if status not in ("not_ready", "completed") and submitted_at is not None:
        waiting_since = max(submitted_at, row["datetime_created"])
        waiting_seconds = max(0, int((now - waiting_since).total_seconds()))

    first_name = row["expert__user__first_name"]
    last_name = row["expert__user__last_name"]
    return {
        "assignment_id": row["id"],
        "expert": {
            "expert_id": row["expert_id"],
            "user_id": row["expert__user_id"],
            "first_name": first_name,
            "last_name": last_name,
            "full_name": " ".join(filter(None, (first_name, last_name))),
            "avatar": row["expert__user__avatar"] or None,
        },
        "project": {"id": row["project_id"], "name": row["project__name"]},
        "status": status,
        "criteria_total": total,
        "criteria_scored": scored,
        "assigned_at": row["datetime_created"],
        "project_submitted": row["project_submitted"],
        "project_submitted_at": submitted_at,
        "waiting_since": waiting_since,
        "waiting_seconds": waiting_seconds,
    }


def build_assignments(program_id):
    now = timezone.now()
    return [build_assignment(row, now=now) for row in assignment_rows(program_id)]


def build_assignment_scores(program_id, assignment):
    scores = dict(
        ProjectScore.objects.filter(
            criteria__partner_program_id=program_id,
            project_id=assignment["project"]["id"],
            user_id=assignment["expert"]["user_id"],
        ).values_list("criteria_id", "value")
    )
    criteria = Criteria.objects.filter(partner_program_id=program_id).order_by("pk")
    return [
        {
            "criterion_id": criterion.pk,
            "name": criterion.name,
            "description": criterion.description,
            "type": criterion.type,
            "min_value": criterion.min_value,
            "max_value": criterion.max_value,
            "value": scores.get(criterion.pk),
            "is_scored": criterion.pk in scores,
        }
        for criterion in criteria
    ]


def build_delayed_experts(assignments):
    experts = {}
    for assignment in assignments:
        expert = assignment["expert"]
        item = experts.setdefault(
            expert["expert_id"],
            {
                **expert,
                "assignments_total": 0,
                "completed": 0,
                "pending": 0,
                "overdue_24h": 0,
                "overdue_48h": 0,
                "oldest_waiting_since": None,
                "oldest_waiting_seconds": None,
            },
        )
        item["assignments_total"] += 1
        item["completed" if assignment["status"] == "completed" else "pending"] += 1
        seconds = assignment["waiting_seconds"]
        if seconds is None:
            continue
        item["overdue_24h"] += int(seconds >= 24 * 3600)
        item["overdue_48h"] += int(seconds >= 48 * 3600)
        if seconds > 0 and (
            item["oldest_waiting_seconds"] is None
            or seconds > item["oldest_waiting_seconds"]
        ):
            item["oldest_waiting_since"] = assignment["waiting_since"]
            item["oldest_waiting_seconds"] = seconds

    items = []
    for item in experts.values():
        if item["overdue_48h"] >= 1:
            item["severity"] = "critical"
        elif item["overdue_24h"] >= 2:
            item["severity"] = "warning"
        else:
            continue
        items.append(item)
    items.sort(
        key=lambda item: (
            item["severity"] != "critical",
            -item["oldest_waiting_seconds"],
            item["expert_id"],
        )
    )
    return {"total": len(items), "items": items}
