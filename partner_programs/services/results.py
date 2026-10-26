"""Organizer results: one calculation for the ranking and its Excel export."""

from collections import defaultdict

from django.utils import timezone
from rest_framework import serializers

from partner_programs.services.case_analytics import project_case_links
from partner_programs.services.case_fields import get_program_case_field
from partner_programs.services.management import person_name
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.evaluation_math import evaluation_totals, assign_places, numeric


class ResultsQuery(serializers.Serializer):
    search = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=200
    )
    case_scope = serializers.ChoiceField(
        choices=["all", "selected", "without_case"], default="all"
    )
    case_name = serializers.CharField(required=False, allow_blank=True, max_length=500)
    order = serializers.ChoiceField(choices=["asc", "desc"], default="desc")
    scope = serializers.ChoiceField(choices=["current", "all"], default="current")
    status = serializers.ChoiceField(
        choices=["all", "complete", "pending"], default="all"
    )


def results_data(program, query, *, project_link_id=None):
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    numeric_criteria = [c for c in criteria if c.type in ("int", "float")]
    field = get_program_case_field(program)
    options = field.get_options_list() if field else []
    if query["case_scope"] == "selected" and query.get("case_name") not in options:
        raise serializers.ValidationError({"case_name": "Выберите существующий кейс."})
    links_query = project_case_links(program, field=field)
    links_query = (
        links_query.filter(submitted=True)
        if project_link_id is None
        else links_query.filter(pk=project_link_id)
    )
    links = list(links_query.select_related("project").order_by("pk"))
    project_ids = [link.project_id for link in links]
    values, people = defaultdict(dict), defaultdict(dict)
    for score in ProjectScore.objects.filter(
        criteria__partner_program=program, project_id__in=project_ids
    ).select_related("user"):
        values[(score.project_id, score.user_id)][score.criteria_id] = score.value
        people[score.project_id][score.user_id] = score.user
    for assignment in ProjectExpertAssignment.objects.filter(
        partner_program=program, project_id__in=project_ids
    ).select_related("expert__user"):
        people[assignment.project_id][assignment.expert.user_id] = assignment.expert.user
    required = program.required_evaluators or program.max_project_rates or 1
    maximum = evaluation_totals(criteria, {})["maximum"]
    buckets = {name: [] for name in [*options, None]}
    for link in links:
        totals = evaluation_totals(
            criteria,
            {
                user_id: values[(link.project_id, user_id)]
                for user_id in people[link.project_id]
            },
        )
        experts = []
        for user_id, user in sorted(people[link.project_id].items()):
            scores = values[(link.project_id, user_id)]
            evaluation = totals["evaluations"][user_id]
            experts.append(
                {
                    "user_id": user_id,
                    "name": person_name(user),
                    "email": user.email,
                    "avatar": user.avatar or None,
                    "complete": evaluation["complete"],
                    "total": evaluation["total"],
                    "values": [
                        {"criterion_id": c.pk, "value": scores.get(c.pk)}
                        for c in criteria
                    ],
                }
            )
        completed = [e for e in experts if e["complete"]]
        score = totals["score"]
        averages = totals["averages"]
        buckets.setdefault(link.case_name, []).append(
            {
                "id": link.pk,
                "project_id": link.project_id,
                "name": link.project.name,
                "case_name": link.case_name,
                "completed": len(completed),
                "required": required,
                "evaluation_complete": link.submitted and len(completed) >= required,
                "ready": link.submitted
                and len(completed) >= required
                and score is not None,
                "score": numeric(score),
                "place": None,
                "averages": averages,
                "experts": experts,
            }
        )
    groups = []
    for case_name, projects in buckets.items():
        # A single-project projection cannot determine a place among its peers.
        if project_link_id is None:
            assign_places(projects, "id")
        if query["scope"] != "all":
            if query["case_scope"] == "selected" and case_name != query.get("case_name"):
                continue
            if query["case_scope"] == "without_case" and case_name is not None:
                continue
            projects = [
                p for p in projects if query["search"].lower() in p["name"].lower()
            ]
            status = query.get("status", "all")
            if status != "all":
                projects = [
                    p
                    for p in projects
                    if p["evaluation_complete"] == (status == "complete")
                ]
        sign = -1 if query["order"] == "desc" else 1
        projects.sort(
            key=lambda p: (
                not p["evaluation_complete"],
                p["score"] is None,
                sign * (p["score"] or 0),
                p["name"].lower(),
                p["id"],
            )
        )
        if projects:
            groups.append({"case_name": case_name, "projects": projects})
    return {
        "program_id": program.pk,
        "program_name": program.name,
        "generated_at": timezone.now(),
        "required_evaluators": required,
        "maximum": numeric(maximum),
        "has_numeric_criteria": bool(numeric_criteria),
        "case_options": options,
        "groups": groups,
        "criteria": [
            {
                "id": c.pk,
                "name": c.name,
                "description": c.description,
                "type": c.type,
                "min_value": c.min_value,
                "max_value": c.max_value,
            }
            for c in criteria
        ],
    }
