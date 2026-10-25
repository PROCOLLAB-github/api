"""Разрешенные публичные материалы без приватной проекции заявки и оценок."""

import math
from urllib.parse import urlsplit

from django.db.models import CharField, Prefetch
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce

from partner_programs.solution_api import iso, user_data
from partner_programs.solution_models import ProgramSolution, ProgramSolutionMember
from partner_programs.solution_schema import VALIDATION_DEFAULTS, empty_value, form_data
from project_rates.solution_evaluation import snapshot_name

OMIT_ANSWER = object()


def public_answer_value(field, value):
    kind = field["type"]
    if kind in ("text", "textarea", "select", "radio"):
        return value if isinstance(value, str) else OMIT_ANSWER
    if kind == "checkbox":
        return value if isinstance(value, bool) else OMIT_ANSWER
    if kind == "number":
        try:
            return (
                value
                if type(value) in (int, float) and math.isfinite(value)
                else OMIT_ANSWER
            )
        except OverflowError:
            return OMIT_ANSWER
    url = value.get("url") if kind == "file" and isinstance(value, dict) else value
    if kind in ("url", "file") and isinstance(url, str):
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme in ("http", "https")
                and parsed.netloc
                and not any(ord(char) < 32 or ord(char) == 127 for char in url)
            ):
                return {"url": url} if kind == "file" else url
        except ValueError:
            pass
    return OMIT_ANSWER


def published_solutions(program, search="", *, with_answers=False):
    query = (
        ProgramSolution.objects.filter(program=program, published_at__isnull=False)
        .select_related("captain")
        .prefetch_related(
            Prefetch(
                "members", queryset=ProgramSolutionMember.objects.select_related("user")
            )
        )
        .order_by("published_at", "pk")
    )
    if search:
        query = query.annotate(
            public_name=Coalesce(
                KeyTextTransform("name", "submission_snapshot"),
                "name",
                output_field=CharField(),
            )
        ).filter(public_name__icontains=search)
    return query.prefetch_related("answers") if with_answers else query


def public_user(value):
    if not isinstance(value, dict):
        return user_data(value)
    return dict(
        id=value["id"],
        first_name=value.get("first_name") or "",
        last_name=value.get("last_name") or "",
        avatar_url=value.get("avatar_url") or None,
    )


def public_team(solution):
    snapshot = solution.submission_snapshot if solution.status == "submitted" else None
    captain_id = (
        snapshot.get("captain_id", solution.captain_id)
        if snapshot
        else solution.captain_id
    )
    sources = (
        snapshot.get("members", [])
        if snapshot
        else [
            dict(user=member.user, role=member.role, specialization=member.specialization)
            for member in solution.members.all()
        ]
    )
    people = {}
    for source in sources:
        user = public_user(source["user"])
        people[user["id"]] = dict(
            user=user,
            role=source.get("role"),
            specialization=source.get("specialization"),
            is_captain=user["id"] == captain_id,
        )
    people.setdefault(
        captain_id,
        dict(
            user=public_user(solution.captain),
            role=None,
            specialization=None,
            is_captain=True,
        ),
    )
    members = [
        people[captain_id],
        *[row for uid, row in people.items() if uid != captain_id],
    ]
    return dict(members=members, accepted_count=len(members))


def application(solution):
    return dict(
        kind="solution",
        program_id=solution.program_id,
        solution_id=solution.pk,
        name=snapshot_name(solution),
    )


def public_card(solution):
    team = public_team(solution)
    return dict(
        application=application(solution),
        published_at=iso(solution.published_at),
        captain=team["members"][0]["user"],
        accepted_count=team["accepted_count"],
    )


def public_fields(fields):
    keys = (
        "id",
        "type",
        "purpose",
        "label",
        "help_text",
        "required",
        "position",
        "options",
    )
    return [
        dict(
            **{key: field[key] for key in keys},
            validation={
                key: field.get("validation", {}).get(key, value)
                for key, value in VALIDATION_DEFAULTS.items()
            },
        )
        for field in fields
    ]


def public_materials(solution):
    snapshot = solution.submission_snapshot if solution.status == "submitted" else None
    if snapshot:
        fields, answers = snapshot["form"]["fields"], snapshot["answers"]
    else:
        fields = form_data(solution.program)["fields"]
        answers = [
            dict(field_id=row.field_id, value=row.value) for row in solution.answers.all()
        ]
    fields = public_fields(fields)
    by_id = {row["id"]: row for row in fields}
    safe_answers = {}
    for row in answers:
        field = by_id.get(row["field_id"])
        if field is None or empty_value(row["value"]):
            continue
        value = public_answer_value(field, row["value"])
        if value is OMIT_ANSWER:
            continue
        safe_answers[row["field_id"]] = dict(field_id=row["field_id"], value=value)
    return dict(
        application=application(solution),
        published_at=iso(solution.published_at),
        fields=fields,
        answers=[
            safe_answers[field["id"]] for field in fields if field["id"] in safe_answers
        ],
        team=public_team(solution),
    )
