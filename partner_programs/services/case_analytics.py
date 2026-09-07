"""Read-only case analytics on existing Project × Program relations."""

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


def build_case_analytics(program) -> dict:
    """Count program links by exact current options of the system field name='case'.

    Missing/empty/obsolete choices share without_case; every link is counted once,
    using only its submitted flag, including in noncompetitive programs. Options
    retain configuration order and zero rows. Team participants are leaders or
    collaborators registered in THIS program, unique within each bucket. A user
    may appear in several cases, so participant totals are not globally additive.
    Four SQL queries (definition, link counts, leader pairs, collaborator pairs),
    independent of option count; serializers perform no queries.
    """
    field = get_program_case_field(program)
    options = field.get_options_list() if field else []
    buckets = {name: _empty_metrics() for name in options}
    without_case = _empty_metrics()
    participant_ids = {name: set() for name in buckets}
    participant_ids[None] = set()

    choice = (
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
        .annotate(case_value=choice)
    )
    for row in links.values("case_value", "submitted").annotate(total=Count("pk")):
        metrics = buckets.get(row["case_value"], without_case)
        metrics["projects_total"] += row["total"]
        metrics["submitted" if row["submitted"] else "not_submitted"] += row["total"]

    registered_users = PartnerProgramUserProfile.objects.filter(
        partner_program_id=program.pk, user_id__isnull=False
    ).values("user_id")
    # IN subqueries do not multiply memberships if legacy profiles are duplicated.
    for user_path in ("project__leader_id", "project__collaborator__user_id"):
        pairs = (
            links.filter(**{f"{user_path}__in": registered_users})
            .values_list("case_value", user_path)
            .distinct()
        )
        for case_value, user_id in pairs:
            bucket = case_value if case_value in buckets else None
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
