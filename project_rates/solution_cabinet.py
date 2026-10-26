"""Общая страница назначений с явным видом заявки и единой пагинацией."""

from datetime import datetime, timezone

from django.utils.dateparse import parse_datetime

from partner_programs.models import PartnerProgram
from partner_programs.solution_api import iso
from project_rates.evaluation_math import complete_values
from project_rates.expert_cabinet import cabinet_projects
from project_rates.models import Criteria
from project_rates.solution_evaluation import metrics, rating_summary


def cabinet_applications(user, query):
    programs = list(
        PartnerProgram.objects.filter(experts__user=user).distinct().order_by("pk")
    )
    legacy = cabinet_projects(
        user,
        query,
        [p.pk for p in programs if p.solution_storage_mode == "legacy_project"],
        paginate=False,
        as_applications=True,
    )
    rows = legacy["results"]
    pending, completed, unavailable = (
        legacy["pending"],
        legacy["completed"],
        legacy["unavailable"],
    )
    for program in programs:
        if program.solution_storage_mode != "solution":
            continue
        assignments = list(
            program.solution_expert_assignments.filter(expert__user=user)
            .select_related("solution")
            .order_by("pk")
        )
        visible = [
            a
            for a in assignments
            if a.solution.program_id == program.pk and a.solution.status == "submitted"
        ]
        unavailable += len(assignments) - len(visible)
        solutions = [a.solution for a in visible]
        criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
        states = metrics(program, solutions, user, criteria)
        for assignment in visible:
            solution = assignment.solution
            state = states[solution.pk]
            done = complete_values(criteria, state["own"])
            completed += done
            pending += not done
            if done != (query["status"] == "completed"):
                continue
            if query.get("program_id") and program.pk != query["program_id"]:
                continue
            summary = rating_summary(program, solution, user, criteria, state)
            if (
                query.get("q", "").casefold()
                not in summary["application"]["name"].casefold()
            ):
                continue
            rows.append(
                dict(
                    application=summary["application"],
                    assignment_id=assignment.pk,
                    program=dict(id=program.pk, name=program.name),
                    deadline=iso(program.datetime_evaluation_ends),
                    case_name=summary["case_name"],
                    is_completed=summary["is_completed"],
                    can_rate=summary["can_rate"],
                    blocked_reason=summary["blocked_reason"],
                )
            )
    rows.sort(
        key=lambda row: (
            row["deadline"] is None,
            parse_datetime(row["deadline"])
            if row["deadline"]
            else datetime.max.replace(tzinfo=timezone.utc),
            row["program"]["id"],
            row["application"]["name"].casefold(),
            row["assignment_id"],
            row["application"]["kind"],
        )
    )
    offset, limit = query["offset"], query["limit"]
    return dict(
        count=len(rows),
        limit=limit,
        offset=offset,
        pending=pending,
        completed=completed,
        unavailable=unavailable,
        results=rows[offset : offset + limit],  # noqa: E203 (black slice formatting)
    )
