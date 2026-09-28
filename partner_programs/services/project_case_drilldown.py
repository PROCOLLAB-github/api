"""Read-only, program-scoped projection shared by the case list and XLSX."""

from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from projects.models import Collaborator

from .case_analytics import project_case_links


def case_project_rows(program, *, field, selection):
    links = project_case_links(program, field=field)
    if selection["case_scope"] == "selected":
        links = links.filter(case_name=selection["case_name"])
    elif selection["case_scope"] == "without_case":
        links = links.filter(case_name__isnull=True)

    collaborators = (
        Collaborator.objects.filter(project_id=OuterRef("project_id"))
        .order_by()
        .values("project_id")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return (
        links.select_related("project", "project__leader")
        .only(
            "id",
            "project_id",
            "datetime_created",
            "submitted",
            "datetime_submitted",
            "project__id",
            "project__name",
            "project__presentation_address",
            "project__region",
            "project__leader_id",
            "project__leader__id",
            "project__leader__first_name",
            "project__leader__last_name",
        )
        .annotate(
            # Keep the legacy export definition: leader + collaborator rows,
            # not unique registered participants from the bucket metrics.
            team_size=Coalesce(
                Subquery(collaborators, output_field=IntegerField()), Value(0)
            )
            + Value(1)
        )
        .order_by("datetime_created", "pk")
    )


def case_list_metadata(cases, selection):
    scope = selection["case_scope"]
    name = selection.get("case_name")
    metrics = None
    if scope == "without_case":
        metrics = cases["without_case"]
    elif scope == "selected":
        bucket = next(item for item in cases["items"] if item["name"] == name)
        metrics = {key: value for key, value in bucket.items() if key != "name"}
    return {
        "selection": {"scope": scope, "case_name": name},
        "cases_configured": cases["configured"],
        "submission_applicable": cases["submission_applicable"],
        "case_metrics": metrics,
    }
