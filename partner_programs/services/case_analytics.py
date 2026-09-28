"""Read-only аналитика кейсов по связям Project × Program."""

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
    """Классифицирует связи по точному совпадению с текущими options.

    NULL обозначает without_case, включая отсутствующие/пустые/устаревшие
    значения. Overview, список и экспорт используют одно выражение без writes.
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
    """Группирует связи выбранной программы по текущим options системного case.

    Четыре ограниченных SELECT загружают definition, счётчики связей,
    зарегистрированных лидеров и участников. Связь входит в один bucket,
    участники уникальны внутри каждого bucket.
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
