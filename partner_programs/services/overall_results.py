"""Общий командный рейтинг: официальный кейс из 100 плюс завершенный квиз из 100."""

from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from partner_programs.overall_models import ProgramQuizOutcome, normalized_stage_score
from partner_programs.services.case_analytics import project_case_links
from partner_programs.services.case_fields import get_program_case_field
from partner_programs.services.results import results_data
from project_rates.evaluation_math import assign_places
from project_rates.scoring import WEIGHTED

STATUS_LABELS = {
    "configuration_required": "Не настроены веса критериев кейса",
    "pending_both": "Ожидает кейс и квиз",
    "pending_case": "Ожидает кейс",
    "pending_quiz": "Ожидает квиз",
    "complete": "В рейтинге",
}


class OverallResultsUnavailable(APIException):
    status_code = 409
    default_code = "overall_results_unavailable"
    default_detail = "Общий рейтинг доступен для конкурсной программы с проектами."


def overall_results_data(program, query):
    if not program.is_competitive or program.solution_storage_mode != "legacy_project":
        raise OverallResultsUnavailable()
    # Оценки кейса считаем тем же сервисом, с теми же экспертами и округлением.
    case_data = results_data(
        program,
        {
            "search": "",
            "case_scope": "all",
            "scope": "all",
            "order": "desc",
            "status": "all",
        },
    )
    case_rows = {
        row["id"]: row for group in case_data["groups"] for row in group["projects"]
    }
    configured = program.evaluation_scoring_mode == WEIGHTED
    links = list(
        project_case_links(program, field=get_program_case_field(program))
        .select_related("project")
        .order_by("pk")
    )
    quizzes = dict(
        ProgramQuizOutcome.objects.filter(
            program=program,
            project_id__in=[link.project_id for link in links],
        ).values_list("project_id", "score")
    )
    rows = []
    for link in links:
        case = case_rows.get(link.pk)
        case_score = (
            normalized_stage_score(case["score"])
            if configured and case and case["score"] is not None
            else None
        )
        case_complete = bool(
            configured and case and case["ready"] and case_score is not None
        )
        quiz_score = quizzes.get(link.project_id)
        quiz_complete = quiz_score is not None
        ready = case_complete and quiz_complete
        case_status = (
            "not_configured"
            if not configured
            else "not_submitted"
            if not link.submitted
            else "complete"
            if case_complete
            else "pending"
        )
        status = (
            "configuration_required"
            if not configured
            else "complete"
            if ready
            else "pending_both"
            if not case_complete and not quiz_complete
            else "pending_case"
            if not case_complete
            else "pending_quiz"
        )
        rows.append(
            {
                "id": link.pk,
                "project_id": link.project_id,
                "name": link.project.name,
                "case_name": link.case_name,
                "submitted": link.submitted,
                "case_score": float(case_score) if case_score is not None else None,
                "case_complete": case_complete,
                "case_status": case_status,
                "case_evaluators_completed": case["completed"] if case else 0,
                "case_evaluators_required": case_data["required_evaluators"],
                "quiz_score": float(quiz_score) if quiz_score is not None else None,
                "quiz_complete": quiz_complete,
                "score": case_score + quiz_score if ready else None,
                "ready": ready,
                "status": status,
                "place": None,
            }
        )
    assign_places(rows, "id")
    total_count, total_ready = len(rows), sum(row["ready"] for row in rows)
    if (
        query["case_scope"] == "selected"
        and query.get("case_name") not in case_data["case_options"]
    ):
        raise ValidationError({"case_name": "Выберите существующий кейс."})
    if query.get("scope", "current") != "all":
        if query["case_scope"] == "selected":
            rows = [row for row in rows if row["case_name"] == query["case_name"]]
        elif query["case_scope"] == "without_case":
            rows = [row for row in rows if row["case_name"] is None]
        rows = [
            row for row in rows if query.get("search", "").lower() in row["name"].lower()
        ]
        if query.get("status", "all") != "all":
            rows = [
                row for row in rows if row["ready"] == (query["status"] == "complete")
            ]
    sign = -1 if query.get("order", "desc") == "desc" else 1
    rows.sort(
        key=lambda row: (
            not row["ready"],
            sign * (row["score"] or Decimal("0")),
            row["name"].lower(),
            row["id"],
        )
    )
    for row in rows:
        if row["score"] is not None:
            row["score"] = float(row["score"])
    return {
        "program_id": program.pk,
        "program_name": program.name,
        "generated_at": timezone.now(),
        "formula": "case_plus_quiz",
        "case_maximum": 100,
        "quiz_maximum": 100,
        "maximum": 200,
        "case_scoring_mode": program.evaluation_scoring_mode,
        "case_scoring_configured": configured,
        "case_options": case_data["case_options"],
        "total_count": total_count,
        "total_ready_count": total_ready,
        "matching_count": len(rows),
        "ready_count": sum(row["ready"] for row in rows),
        "projects": rows,
    }
