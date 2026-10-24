"""Оценка сданных решений с общими критериями и прежними режимами программы."""

from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from partner_programs.solution_errors import SolutionError, issue
from partner_programs.solution_models import ProgramSolution
from partner_programs.solution_team import lock_solution
from project_rates.criteria_policy import revision as criteria_revision, mark_locked
from project_rates.models import Criteria
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.evaluation_math import complete_values, valid_score as valid_value
from users.models import Expert


def program_expert(program, actor, *, required=True):
    expert = Expert.objects.filter(
        programs=program, user=actor, user__is_active=True
    ).first()
    if not expert and required:
        raise SolutionError(
            "not_program_expert",
            "Оценивание доступно экспертам этой программы.",
            status=403,
        )
    return expert


def expert_visible_solutions(program, actor):
    query = ProgramSolution.objects.filter(program=program, status="submitted")
    expert = program_expert(program, actor, required=False)
    if not expert:
        return query.none()
    if program.is_distributed_evaluation:
        query = query.filter(
            expert_assignments__partner_program=program, expert_assignments__expert=expert
        )
    return query.distinct()


def snapshot_name(solution):
    snapshot = solution.submission_snapshot or {}
    return snapshot.get("name", solution.name)


def snapshot_case(solution, *, draft_field_id=None):
    snapshot = solution.submission_snapshot or {}
    if solution.status == "submitted":
        field = next(
            (
                field
                for field in snapshot.get("form", {}).get("fields", [])
                if field["purpose"] == "case"
            ),
            None,
        )
        value = next(
            (
                answer["value"]
                for answer in snapshot.get("answers", [])
                if field and answer["field_id"] == field["id"]
            ),
            None,
        )
    else:
        value = next(
            (
                answer.value
                for answer in solution.answers.all()
                if answer.field_id == draft_field_id
            ),
            None,
        )
    return value if isinstance(value, str) and value.strip() else None


def team_user_ids(solution):
    if solution.status == "submitted":
        snapshot = solution.submission_snapshot or {}
        return {snapshot.get("captain_id", solution.captain_id)} | {
            row["user"]["id"] for row in snapshot.get("members", [])
        }
    return {solution.captain_id} | {member.user_id for member in solution.members.all()}


def metrics(program, solutions, actor, criteria):
    ids = [solution.pk for solution in solutions]
    values = defaultdict(lambda: defaultdict(dict))
    for solution_id, user_id, criterion_id, value in SolutionScore.objects.filter(
        solution_id__in=ids, criteria__partner_program=program
    ).values_list("solution_id", "user_id", "criteria_id", "value"):
        values[solution_id][user_id][criterion_id] = value
    assigned = set(
        SolutionExpertAssignment.objects.filter(
            partner_program=program, solution_id__in=ids, expert__user=actor
        ).values_list("solution_id", flat=True)
    )
    return {
        solution.pk: dict(
            own=values[solution.pk].get(actor.pk, {}),
            assigned=solution.pk in assigned,
            any_count=len(values[solution.pk]),
            completed_count=sum(
                complete_values(criteria, scores)
                for scores in values[solution.pk].values()
            ),
        )
        for solution in solutions
    }


def blocked_reason(program, solution, actor, criteria, state):
    if program.solution_storage_mode != "solution":
        return "Программа использует заявки на основе проектов."
    if solution.status != "submitted":
        return "Сначала нужно сдать решение."
    if (
        program.datetime_evaluation_ends
        and timezone.now() > program.datetime_evaluation_ends
    ):
        return "Срок оценивания завершен."
    if not criteria:
        return "Организатор еще не настроил критерии."
    if program.is_distributed_evaluation and not state["assigned"]:
        return "Решение не назначено вам для оценки."
    if program.required_evaluators is not None and actor.pk in team_user_ids(solution):
        return "Нельзя оценивать решение своей команды."
    if (
        program.required_evaluators is None
        and program.max_project_rates
        and state["any_count"] >= program.max_project_rates
        and not state["own"]
    ):
        return "Лимит оценок достигнут."
    return None


def rating_summary(program, solution, actor, criteria, state):
    reason = blocked_reason(program, solution, actor, criteria, state)
    return dict(
        application=dict(
            kind="solution",
            program_id=program.pk,
            solution_id=solution.pk,
            name=snapshot_name(solution),
        ),
        case_name=snapshot_case(solution),
        assigned=state["assigned"],
        is_completed=complete_values(criteria, state["own"]),
        can_rate=reason is None,
        blocked_reason=reason,
    )


def rating_frame(solution, actor):
    from partner_programs.solution_api import solution_data, iso

    program = solution.program
    program_expert(program, actor)
    if solution.status != "submitted":
        raise SolutionError("solution_not_submitted", "Сначала нужно сдать решение.")
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    state = metrics(program, [solution], actor, criteria)[solution.pk]
    reason = blocked_reason(program, solution, actor, criteria, state)
    return dict(
        program=dict(id=program.pk, name=program.name),
        solution=solution_data(solution, actor),
        criteria_revision=criteria_revision(program),
        criteria=[
            dict(
                id=c.pk,
                name=c.name,
                description=c.description,
                type=c.type,
                min_value=c.min_value,
                max_value=c.max_value,
                value=state["own"].get(c.pk),
            )
            for c in criteria
        ],
        managed_evaluation=program.required_evaluators is not None,
        can_rate=reason is None,
        blocked_reason=reason,
        is_completed=complete_values(criteria, state["own"]),
        rated_count=state["completed_count"]
        if program.required_evaluators is not None
        else state["any_count"],
        max_rates=program.max_project_rates,
        required_evaluators=program.required_evaluators or program.max_project_rates or 1,
        deadline=iso(program.datetime_evaluation_ends),
    )


def list_ratings(program, actor, query):
    program_expert(program, actor)
    solutions = list(
        expert_visible_solutions(program, actor).select_related("program").order_by("pk")
    )
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    states = metrics(program, solutions, actor, criteria)
    if query["case_scope"] == "selected":
        field = program.fields.filter(name="case").first()
        if not field or query.get("case_name") not in field.get_options_list():
            raise SolutionError(
                "invalid_filter", "Выберите кейс этой программы.", status=400
            )
    rows = []
    for solution in solutions:
        row = rating_summary(program, solution, actor, criteria, states[solution.pk])
        if query["search"].casefold() not in row["application"]["name"].casefold():
            continue
        if query["assigned_only"] and not row["assigned"]:
            continue
        if query["status"] != "all" and row["is_completed"] != (
            query["status"] == "completed"
        ):
            continue
        if query["case_scope"] == "selected" and row["case_name"] != query.get(
            "case_name"
        ):
            continue
        if query["case_scope"] == "without_case" and row["case_name"] is not None:
            continue
        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["application"]["name"].casefold(),
            row["application"]["solution_id"],
        )
    )
    offset, limit = query["offset"], query["limit"]
    return len(rows), rows[offset : offset + limit]  # noqa: E203 (black slice formatting)


def score_issue(criterion_id, code, detail):
    return {
        **issue(f"scores.{criterion_id}.value", code, detail),
        "criterion_id": criterion_id,
    }


@transaction.atomic
def rate_solution(*, program_id, solution_id, actor, expected_criteria_revision, scores):
    solution = lock_solution(program_id, solution_id, actor)
    program = solution.program
    program_expert(program, actor)
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    if solution.status != "submitted":
        raise SolutionError("solution_not_submitted", "Сначала нужно сдать решение.")
    actual_revision = criteria_revision(program)
    if expected_criteria_revision != actual_revision:
        raise SolutionError(
            "criteria_changed",
            "Критерии изменились. Обновите форму оценки.",
            meta={"current_criteria_revision": actual_revision},
        )
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    definitions = {c.pk: c for c in criteria}
    state = metrics(program, [solution], actor, criteria)[solution.pk]
    reason = blocked_reason(program, solution, actor, criteria, state)
    if reason:
        if (
            program.datetime_evaluation_ends
            and timezone.now() > program.datetime_evaluation_ends
        ):
            code = "evaluation_closed"
        elif not criteria:
            code = "criteria_not_configured"
        elif program.required_evaluators is not None and actor.pk in team_user_ids(
            solution
        ):
            code = "own_team"
        elif program.is_distributed_evaluation and not state["assigned"]:
            code = "not_assigned"
        else:
            code = "max_rates_reached"
        raise SolutionError(
            code, reason, status=403 if code in ("own_team", "not_assigned") else 409
        )
    if not isinstance(scores, list) or not scores:
        raise SolutionError(
            "invalid_scores", "Передайте непустой список оценок.", status=400
        )
    seen, problems, values = set(), [], {}
    for row in scores:
        pk, value = row["criterion_id"], row["value"]
        if pk in seen:
            problems.append(
                score_issue(pk, "duplicate_criterion", "Критерий повторяется в запросе.")
            )
            continue
        seen.add(pk)
        if pk not in definitions:
            problems.append(
                score_issue(
                    pk, "unknown_criterion", "Критерий не относится к этой программе."
                )
            )
            continue
        if (
            value is not None and (not isinstance(value, str) or len(value) > 50)
        ) or not valid_value(definitions[pk], value):
            problems.append(
                score_issue(
                    pk, "invalid_value", "Проверьте тип ответа и допустимый диапазон."
                )
            )
            continue
        values[pk] = value
    if program.required_evaluators is not None:
        for criterion in criteria:
            if criterion.type != "str" and criterion.pk not in seen:
                problems.append(
                    score_issue(
                        criterion.pk, "required", "Заполните обязательный критерий."
                    )
                )
            elif criterion.type == "str" and criterion.pk not in seen:
                values[criterion.pk] = ""
    if problems:
        raise SolutionError(
            "invalid_scores", "Проверьте критерии оценки.", status=400, errors=problems
        )
    SolutionScore.objects.bulk_create(
        [
            SolutionScore(solution=solution, user=actor, criteria_id=pk, value=value)
            for pk, value in values.items()
        ],
        update_conflicts=True,
        update_fields=["value"],
        unique_fields=["criteria", "user", "solution"],
    )
    mark_locked(program)
    from project_rates.solution_notifications import notify_solution_rated

    notify_solution_rated(solution)
    return solution
