"""Выбор решений и настоящих незавершенных назначений для напоминания."""

from django.db.models import CharField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from partner_programs.serializers.attention_actions import MAX_SELECTION
from partner_programs.services.solution_analytics import SolutionAnalyticsContext
from partner_programs.solution_models import ProgramSolution
from project_rates.solution_models import SolutionExpertAssignment

SOLUTION_AWAITING = "solutions-awaiting-evaluation"


def solution_reminder_rows(program, payload):
    if not (
        program.solution_storage_mode == "solution"
        and program.is_competitive
        and program.is_distributed_evaluation
    ):
        return []
    query = ProgramSolution.objects.filter(program=program, status="submitted")
    if payload["search"]:
        query = query.annotate(
            attention_name=Coalesce(
                KeyTextTransform("name", "submission_snapshot"),
                "name",
                output_field=CharField(),
            )
        ).filter(attention_name__icontains=payload["search"])
    selection = payload["selection"]
    if selection["mode"] == "selected":
        query = query.filter(pk__in=selection["ids"])
    else:
        query = query.exclude(pk__in=selection["excluded_ids"])
    ids = list(query.order_by("submitted_at", "pk").values_list("pk", flat=True))
    if not ids:
        return []
    context = SolutionAnalyticsContext(program, solution_ids=ids)
    rows = {
        solution.pk: dict(
            application=context.application(solution),
            pending_assignments=[
                row
                for row in context.assignments_by_solution[solution.pk]
                if row["status"] in ("pending", "in_progress")
            ],
        )
        for solution in context.solutions
        if context.state(solution) in ("awaiting_evaluation", "partially_evaluated")
    }
    if len(rows) > MAX_SELECTION:
        raise ValidationError(
            {
                "detail": f"За один раз можно выбрать до {MAX_SELECTION} строк. Уточните поиск."
            }
        )
    return [rows[solution_id] for solution_id in ids if solution_id in rows]


def solution_recipient_targets(program, rows):
    assignment_sources = solution_assignment_sources(rows)
    assignments = (
        SolutionExpertAssignment.objects.filter(
            pk__in=assignment_sources,
            partner_program=program,
            solution__program=program,
            solution__status="submitted",
            solution__archived_at__isnull=True,
            expert__programs=program,
            expert__user__is_active=True,
        )
        .order_by("pk")
        .values("pk", "solution_id", "expert__user_id")
    )
    targets = {}
    for assignment in assignments:
        uid = assignment["expert__user_id"]
        target = targets.setdefault(
            uid, {"user_id": uid, "source_ids": [], "assignment_ids": []}
        )
        if assignment["solution_id"] not in target["source_ids"]:
            target["source_ids"].append(assignment["solution_id"])
        target["assignment_ids"].append(assignment["pk"])
    return list(targets.values())


def solution_assignment_sources(rows):
    return {
        assignment["assignment_id"]: row["application"]["solution_id"]
        for row in rows
        for assignment in row["pending_assignments"]
    }
