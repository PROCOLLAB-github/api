"""Read-only case analytics for legacy Project links in one program."""

from django.db.models import Count, OuterRef, Subquery, TextField, Value

from partner_programs.models import (
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.services.case_fields import get_program_case_field


def _empty_metrics():
    return {
        "participants_total": 0,
        "projects_total": 0,
        "not_submitted": 0,
        "submitted": 0,
    }


def build_project_case_analytics(program) -> dict:
    """Group current-program links by exact current system case options.

    Four bounded SELECTs load the case definition, grouped link counts,
    registered leaders and registered collaborators. Every link belongs to one
    project bucket; participants are unique inside each bucket.
    """
    field = get_program_case_field(program)
    options = field.get_options_list() if field else []
    buckets = {name: _empty_metrics() for name in options}
    without_case = _empty_metrics()
    participant_ids = {name: set() for name in buckets}
    participant_ids[None] = set()

    case_value = (
        Subquery(
            PartnerProgramFieldValue.objects.filter(
                program_project_id=OuterRef("pk"), field_id=field.pk
            ).values("value_text")[:1]
        )
        if field
        else Value(None, output_field=TextField())
    )
    links = (
        PartnerProgramProject.objects.filter(partner_program_id=program.pk)
        .order_by()
        .annotate(case_value=case_value)
    )
    for row in links.values("case_value", "submitted").annotate(total=Count("pk")):
        metrics = buckets.get(row["case_value"], without_case)
        metrics["projects_total"] += row["total"]
        metrics["submitted" if row["submitted"] else "not_submitted"] += row["total"]

    registered_users = PartnerProgramUserProfile.objects.filter(
        partner_program_id=program.pk, user_id__isnull=False
    ).values("user_id")
    for user_path in ("project__leader_id", "project__collaborator__user_id"):
        pairs = (
            links.filter(**{f"{user_path}__in": registered_users})
            .values_list("case_value", user_path)
            .distinct()
        )
        for value, user_id in pairs:
            bucket = value if value in buckets else None
            participant_ids[bucket].add(user_id)

    for name, metrics in buckets.items():
        metrics["participants_total"] = len(participant_ids[name])
    without_case["participants_total"] = len(participant_ids[None])
    return {
        "configured": field is not None,
        "submission_applicable": program.is_competitive,
        "items": [{"name": name, **metrics} for name, metrics in buckets.items()],
        "without_case": without_case,
    }
