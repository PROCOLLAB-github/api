"""Organizer results: one calculation for the ranking and its Excel export."""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone
from rest_framework import serializers

from partner_programs.services.case_analytics import project_case_links
from partner_programs.services.case_fields import get_program_case_field
from partner_programs.services.management import person_name
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.validators import ProjectScoreValidator


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


def rounded(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def numeric(value):
    return float(value) if value is not None else None


def valid_score(criterion, value):
    try:
        ProjectScoreValidator.validate(
            criteria_type=criterion.type,
            value=value,
            criteria_min_value=criterion.min_value,
            criteria_max_value=criterion.max_value,
        )
        return True
    except (TypeError, ValueError):
        return False


def results_data(program, query):
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    numeric_criteria = [c for c in criteria if c.type in ("int", "float")]
    field = get_program_case_field(program)
    options = field.get_options_list() if field else []
    if query["case_scope"] == "selected" and query.get("case_name") not in options:
        raise serializers.ValidationError({"case_name": "Выберите существующий кейс."})
    links = list(
        project_case_links(program, field=field)
        .filter(submitted=True)
        .select_related("project")
        .order_by("pk")
    )
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
    maximum = (
        sum(Decimal(str(c.max_value)) for c in numeric_criteria)
        if numeric_criteria and all(c.max_value is not None for c in numeric_criteria)
        else None
    )
    buckets = {name: [] for name in [*options, None]}
    for link in links:
        experts = []
        for user_id, user in sorted(people[link.project_id].items()):
            scores = values[(link.project_id, user_id)]
            complete = bool(criteria) and all(
                c.pk in scores and valid_score(c, scores[c.pk]) for c in criteria
            )
            total = (
                sum(Decimal(scores[c.pk]) for c in numeric_criteria)
                if complete and numeric_criteria
                else None
            )
            experts.append(
                {
                    "user_id": user_id,
                    "name": person_name(user),
                    "email": user.email,
                    "avatar": user.avatar or None,
                    "complete": complete,
                    "total": numeric(total),
                    "values": [
                        {"criterion_id": c.pk, "value": scores.get(c.pk)}
                        for c in criteria
                    ],
                }
            )
        completed = [e for e in experts if e["complete"]]
        score = (
            rounded(sum(Decimal(str(e["total"])) for e in completed) / len(completed))
            if completed and numeric_criteria
            else None
        )
        averages = {
            str(c.pk): numeric(
                rounded(
                    sum(
                        Decimal(values[(link.project_id, e["user_id"])][c.pk])
                        for e in completed
                    )
                    / len(completed)
                )
            )
            for c in numeric_criteria
            if completed
        }
        buckets.setdefault(link.case_name, []).append(
            {
                "id": link.pk,
                "project_id": link.project_id,
                "name": link.project.name,
                "case_name": link.case_name,
                "completed": len(completed),
                "required": required,
                "ready": len(completed) >= required and score is not None,
                "score": numeric(score),
                "place": None,
                "averages": averages,
                "experts": experts,
            }
        )
    groups = []
    for case_name, projects in buckets.items():
        ready = sorted(
            [p for p in projects if p["ready"]],
            key=lambda p: (-p["score"], p["name"].lower(), p["id"]),
        )
        last_score, place = None, 0
        for index, project in enumerate(ready, 1):
            if project["score"] != last_score:
                place = index
            project["place"] = place
            last_score = project["score"]
        if query["scope"] != "all":
            if query["case_scope"] == "selected" and case_name != query.get("case_name"):
                continue
            if query["case_scope"] == "without_case" and case_name is not None:
                continue
            projects = [
                p for p in projects if query["search"].lower() in p["name"].lower()
            ]
        sign = -1 if query["order"] == "desc" else 1
        projects.sort(
            key=lambda p: (
                not p["ready"],
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
