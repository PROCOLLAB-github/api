"""Компактная аналитика текущего пользователя без публикации чужих результатов."""

from django.db.models import Count, Exists, OuterRef, Q
from rest_framework.exceptions import APIException, PermissionDenied

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.services.analytics import _get_participant_metrics
from partner_programs.services.analytics import _get_solution_metrics
from partner_programs.services.analytics import _solution_rows
from partner_programs.services.assignment_analytics import annotated_assignment_queryset
from partner_programs.services.case_fields import get_program_case_field
from project_rates.models import ProjectScore
from projects.models import Collaborator


def program_widget_role(program, user):
    """Роль только в этой программе; назначения и глобальный user_type не участвуют."""
    if not user or not user.is_authenticated:
        return None
    if program.is_manager(user):
        return "organizer"
    if program.experts.filter(user_id=user.pk).exists():
        return "expert"
    if PartnerProgramUserProfile.objects.filter(
        partner_program_id=program.pk, user_id=user.pk
    ).exists():
        return "participant"
    return None


def organizer_widget_metrics(program):
    """Та же единица учёта и предикаты, что у manager-overview, без его детализаций."""
    participants = _get_participant_metrics(program.pk)
    solutions = _get_solution_metrics(program)
    return {
        "participants": participants["unique_participants"],
        "projects": solutions["created"],
        "submitted_solutions": solutions["submitted"] if program.is_competitive else None,
        "participants_without_project": participants["without_team"],
    }


def expert_widget_metrics(program, user):
    """Остаток по назначениям, включая not_ready; нулевая оценка уже учтена общим SQL."""
    mode = "distributed" if program.is_distributed_evaluation else "open"
    if mode == "open" or not program.is_competitive:
        return {"mode": mode, "assigned": None, "remaining": None}
    counts = (
        annotated_assignment_queryset(program.pk)
        .filter(expert__user_id=user.pk)
        .aggregate(
            assigned=Count("pk"),
            remaining=Count("pk", filter=Q(is_completed=False)),
        )
    )
    return {"mode": mode, **counts}


def require_widget_role(program, user):
    """Проверка GET-контракта не меняет регистрации, назначения или бизнес-данные."""
    role = program_widget_role(program, user)
    if role is None:
        raise PermissionDenied("Аналитика доступна только участникам этой программы.")
    return role


def participant_project_links(program, user):
    """Только лидер и действующий Collaborator; чужие программы и приглашения исключены."""
    team = Collaborator.objects.filter(project_id=OuterRef("project_id"), user_id=user.pk)
    return (
        PartnerProgramProject.objects.filter(partner_program_id=program.pk)
        .annotate(is_team_member=Exists(team))
        .filter(Q(project__leader_id=user.pk) | Q(is_team_member=True))
    )


class ParticipantProjectIntegrityError(APIException):
    status_code = 409
    default_detail = "Связи проекта команды требуют проверки организатором."
    default_code = "participant_project_integrity_error"


def participant_widget_metrics(program, user):
    """Единственный проект команды в программе, независимо от legacy current_application.

    Читаем максимум две связи для обнаружения нарушения правила одной команды.
    Не выбираем первую запись и не меняем данные. Возвращаем только стадию
    общей аналитики, без оценок, экспертов или неопубликованных результатов.
    """
    links = participant_project_links(program, user)
    link_ids = list(links.order_by("pk").values_list("pk", flat=True)[:2])
    if len(link_ids) > 1:
        raise ParticipantProjectIntegrityError()
    link_id = link_ids[0] if link_ids else None

    case_field = get_program_case_field(program)
    result = {
        "participant_project": None,
        "case_provided": case_field is not None,
        "case_name": None,
        "stage": "not_applicable" if not program.is_competitive else "none",
        "submission_open": program.is_project_submission_open(),
    }
    if link_id is None:
        return result
    link = _solution_rows(program).select_related("project").get(pk=link_id)
    result["participant_project"] = {
        "id": link.project_id,
        "name": link.project.name,
        "program_link_id": link.pk,
    }
    if case_field:
        result["case_name"] = (
            link.field_values.filter(field=case_field)
            .values_list("value_text", flat=True)
            .first()
            or None
        )
    if program.is_competitive:
        if not link.submitted:
            result["stage"] = "not_submitted"
        elif link.status == "evaluated":
            result["stage"] = "evaluated"
        elif (link.assignments_total or 0) > 0 or ProjectScore.objects.filter(
            project_id=link.project_id, criteria__partner_program_id=program.pk
        ).exists():
            result["stage"] = "review"
        else:
            result["stage"] = "submitted"
    return result


def build_program_role_widget(program, user):
    role = require_widget_role(program, user)
    result = {
        "program_id": program.pk,
        "role": role,
        "is_competitive": program.is_competitive,
    }
    if role == "organizer":
        result["organizer"] = organizer_widget_metrics(program)
    elif role == "expert":
        result["expert"] = {
            **expert_widget_metrics(program, user),
            "evaluation_ends": program.datetime_evaluation_ends,
        }
    else:
        result["participant"] = participant_widget_metrics(program, user)
    return result
