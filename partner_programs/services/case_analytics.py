"""Read-only case analytics for legacy Project links in one program."""

from django.db.models import Case, Count, F, OuterRef, Subquery, TextField, Value, When

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


_UNSET = object()


def project_case_links(program, *, field):
    """Classify every Project × Program link against exact current options.

    NULL is the typed without_case bucket, including missing/blank/obsolete
    values. Overview, list and export all use this expression without writes.
    """
    options = field.get_options_list() if field else []
    case_value = (
        Subquery(
            PartnerProgramFieldValue.objects.filter(
                program_project_id=OuterRef("pk"), field_id=field.pk
            ).values("value_text")[:1]
        )
        if field
        else Value(None, output_field=TextField())
    )
    return (
        PartnerProgramProject.objects.filter(partner_program_id=program.pk)
        .order_by()
        .annotate(case_value=case_value)
        .annotate(
            case_name=Case(
                When(case_value__in=options, then=F("case_value")),
                default=Value(None),
                output_field=TextField(),
            )
        )
    )


def build_case_analytics(program, *, field=_UNSET) -> dict:
    """Group current-program links by exact current system case options.

    Four bounded SELECTs load the case definition, grouped link counts,
    registered leaders and registered collaborators. Every link belongs to one
    project bucket; participants are unique inside each bucket.
    """
    if field is _UNSET:
        field = get_program_case_field(program)
    options = field.get_options_list() if field else []
    buckets = {name: _empty_metrics() for name in options}
    without_case = _empty_metrics()
    participant_ids = {name: set() for name in buckets}
    participant_ids[None] = set()

    links = project_case_links(program, field=field)
    for row in links.values("case_name", "submitted").annotate(total=Count("pk")):
        metrics = buckets.get(row["case_name"], without_case)
        metrics["projects_total"] += row["total"]
        metrics["submitted" if row["submitted"] else "not_submitted"] += row["total"]

    registered_users = PartnerProgramUserProfile.objects.filter(
        partner_program_id=program.pk, user_id__isnull=False
    ).values("user_id")
    for user_path in ("project__leader_id", "project__collaborator__user_id"):
        pairs = (
            links.filter(**{f"{user_path}__in": registered_users})
            .values_list("case_name", user_path)
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
