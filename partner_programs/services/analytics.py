from datetime import timedelta

from django.db.models import Case, CharField, Count, Exists, F, IntegerField, Min
from django.db.models import OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, TruncDate, Trim
from django.utils import timezone

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from projects.models import Collaborator
from partner_programs.services.assignment_analytics import (
    annotated_assignment_queryset,
    build_assignments,
    build_delayed_experts,
)
from project_rates.models import ProjectScore

ACTIVITY_DAYS = 30


def _participant_profiles(program_id):
    """Регистрации с признаками команды только в проектах текущей программы.

    Руководитель считается участником команды и без записи Collaborator.
    Поле project регистрационной анкеты не заменяет фактические связи команды.
    """
    leader_exists = Exists(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            project__leader_id=OuterRef("user_id"),
        )
    )
    submitted_leader_exists = Exists(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            project__leader_id=OuterRef("user_id"),
            submitted=True,
        )
    )
    collaborator_exists = Exists(
        Collaborator.objects.filter(
            user_id=OuterRef("user_id"),
            project__program_links__partner_program_id=program_id,
        )
    )
    return PartnerProgramUserProfile.objects.filter(
        partner_program_id=program_id
    ).annotate(
        is_project_leader=leader_exists,
        is_submitted_project_leader=submitted_leader_exists,
        is_project_collaborator=collaborator_exists,
    )


def _without_team_filter():
    """Общий предикат уникального участника без команды для счётчика и списка."""
    return Q(
        user_id__isnull=False,
        is_project_leader=False,
        is_project_collaborator=False,
    )


def participants_without_team_rows(program_id):
    """Уникальные пользователи без команды с первой регистрацией в программе.

    Группировка сохраняет одну строку на user_id даже при исторических дублях.
    Удалённые пользователи исключены; поиск и пагинация остаются на уровне SQL.
    """
    return (
        _participant_profiles(program_id)
        .filter(_without_team_filter())
        .order_by()
        .values(
            "user_id",
            "user__first_name",
            "user__last_name",
            "user__avatar",
            "user__city",
        )
        .annotate(registered_at=Min("datetime_created"))
    )


def _get_participant_metrics(program_id: int) -> dict[str, int]:
    profiles = _participant_profiles(program_id)
    participant_filter = Q(user_id__isnull=False)
    team_filter = Q(is_project_leader=True) | Q(is_project_collaborator=True)

    return profiles.aggregate(
        registrations=Count("id"),
        unique_participants=Count(
            "user_id",
            filter=participant_filter,
            distinct=True,
        ),
        with_team=Count(
            "user_id",
            filter=participant_filter & team_filter,
            distinct=True,
        ),
        without_team=Count(
            "user_id",
            filter=_without_team_filter(),
            distinct=True,
        ),
        project_creators=Count(
            "user_id",
            filter=participant_filter & Q(is_project_leader=True),
            distinct=True,
        ),
        submitted_project_creators=Count(
            "user_id",
            filter=participant_filter & Q(is_submitted_project_leader=True),
            distinct=True,
        ),
    )


def _get_regions(program_id: int) -> list[dict]:
    return list(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            project__region__isnull=False,
        )
        .annotate(name=Trim("project__region"))
        .exclude(name="")
        .values("name")
        .annotate(count=Count("project_id", distinct=True))
        .order_by("-count", "name")
    )


def _get_participant_regions(program_id: int) -> list[dict]:
    return list(
        PartnerProgramUserProfile.objects.filter(
            partner_program_id=program_id,
            user_id__isnull=False,
            user__city__isnull=False,
        )
        .annotate(name=Trim("user__city"))
        .exclude(name="")
        .values("name")
        .annotate(count=Count("user_id", distinct=True))
        .order_by("-count", "name")
    )


def _solution_rows(program):
    """Общая SQL-классификация работ программы для overview и детализации.

    В distributed учитываются только реальные назначения и общая проверка
    завершённости каждого назначения. В open достаточно первой оценки по
    критериям программы; прогресс назначений в этом режиме неприменим (null).
    """
    rows = PartnerProgramProject.objects.filter(partner_program_id=program.pk)
    if program.is_distributed_evaluation:
        assignment_totals = (
            annotated_assignment_queryset(program.pk)
            .filter(project_id=OuterRef("project_id"))
            .order_by()
            .values("project_id")
            .annotate(
                total=Count("pk"),
                completed=Count("pk", filter=Q(is_completed=True)),
            )
        )
        rows = rows.annotate(
            assignments_total=Coalesce(
                Subquery(assignment_totals.values("total")[:1]), 0
            ),
            assignments_completed=Coalesce(
                Subquery(assignment_totals.values("completed")[:1]), 0
            ),
        )
        evaluated_status = Case(
            When(
                Q(assignments_total=0) | Q(assignments_completed=0),
                then=Value("awaiting_evaluation"),
            ),
            When(
                assignments_completed__lt=F("assignments_total"),
                then=Value("partially_evaluated"),
            ),
            default=Value("evaluated"),
            output_field=CharField(),
        )
    else:
        rows = rows.annotate(
            assignments_total=Value(None, output_field=IntegerField()),
            assignments_completed=Value(None, output_field=IntegerField()),
            has_program_score=Exists(
                ProjectScore.objects.filter(
                    project_id=OuterRef("project_id"),
                    criteria__partner_program_id=program.pk,
                )
            ),
        )
        evaluated_status = Case(
            When(has_program_score=True, then=Value("evaluated")),
            default=Value("awaiting_evaluation"),
            output_field=CharField(),
        )
    return rows.annotate(
        status=Case(
            When(submitted=False, then=Value("not_submitted")),
            default=evaluated_status,
            output_field=CharField(),
        )
    )


def projects_awaiting_evaluation_rows(program):
    """Сданные работы, из которых состоит счётчик ожидания оценивания.

    Одна строка соответствует связи проекта с программой, а не назначению.
    Фильтрация, count и пагинация выполняются в SQL; руководитель загружается
    тем же запросом без полного пользовательского сериализатора или N+1.
    """
    return (
        _solution_rows(program)
        .filter(status__in=("awaiting_evaluation", "partially_evaluated"))
        .select_related("project", "project__leader")
        .only(
            "id",
            "project_id",
            "datetime_submitted",
            "project__name",
            "project__leader_id",
            "project__leader__id",
            "project__leader__first_name",
            "project__leader__last_name",
            "project__leader__avatar",
        )
    )


def _get_solution_metrics(program) -> dict[str, int]:
    return _solution_rows(program).aggregate(
        created=Count("pk"),
        not_submitted=Count("pk", filter=Q(submitted=False)),
        submitted=Count("pk", filter=Q(submitted=True)),
        awaiting_evaluation=Count("pk", filter=Q(status="awaiting_evaluation")),
        partially_evaluated=Count("pk", filter=Q(status="partially_evaluated")),
        evaluated=Count("pk", filter=Q(status="evaluated")),
    )


def _get_assignment_metrics(assignments: list[dict]) -> dict[str, int]:
    metrics = {"total": 0, "pending": 0, "evaluated": 0}
    for assignment in assignments:
        completed = assignment["status"] == "completed"
        metrics["total"] += 1
        metrics["evaluated" if completed else "pending"] += 1
    return metrics


def _get_activity(program_id: int) -> list[dict]:
    today = timezone.localdate()
    start_date = today - timedelta(days=ACTIVITY_DAYS - 1)

    registrations = dict(
        PartnerProgramUserProfile.objects.filter(
            partner_program_id=program_id,
            datetime_created__date__gte=start_date,
            datetime_created__date__lte=today,
        )
        .annotate(activity_date=TruncDate("datetime_created"))
        .values("activity_date")
        .annotate(total=Count("id"))
        .values_list("activity_date", "total")
    )
    submissions = dict(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            submitted=True,
            datetime_submitted__date__gte=start_date,
            datetime_submitted__date__lte=today,
        )
        .annotate(activity_date=TruncDate("datetime_submitted"))
        .values("activity_date")
        .annotate(total=Count("id"))
        .values_list("activity_date", "total")
    )

    return [
        {
            "date": activity_date,
            "registrations": registrations.get(activity_date, 0),
            "submitted_solutions": submissions.get(activity_date, 0),
        }
        for activity_date in (
            start_date + timedelta(days=offset) for offset in range(ACTIVITY_DAYS)
        )
    ]


def build_program_manager_analytics(program) -> dict:
    program_id = program.id
    participants = _get_participant_metrics(program_id)
    regions = _get_regions(program_id)
    participant_regions = _get_participant_regions(program_id)
    assignment_items = build_assignments(program_id)
    assignments = _get_assignment_metrics(assignment_items)
    solutions = _get_solution_metrics(program)

    projects_awaiting_evaluation = (
        solutions["awaiting_evaluation"] + solutions["partially_evaluated"]
    )

    return {
        "summary": {
            "participants": {"total": participants["unique_participants"]},
            "projects": {"total": solutions["created"]},
            "experts": {"total": program.experts.count()},
            "regions": {"total": len(regions), "items": regions},
            "participant_regions": {
                "total": len(participant_regions),
                "items": participant_regions,
            },
        },
        "participant_funnel": {
            "registrations": participants["registrations"],
            "unique_participants": participants["unique_participants"],
            "with_team": participants["with_team"],
            "project_creators": participants["project_creators"],
            "submitted_project_creators": participants["submitted_project_creators"],
        },
        "solution_funnel": {
            "created": solutions["created"],
            "not_submitted": solutions["not_submitted"],
            "submitted": solutions["submitted"],
            "evaluated": solutions["evaluated"],
        },
        "evaluation_status": {
            "mode": ("distributed" if program.is_distributed_evaluation else "open"),
            "max_evaluations_per_project": program.max_project_rates,
            "assignments": {
                "total": assignments["total"],
                "pending": assignments["pending"],
                "evaluated": assignments["evaluated"],
            },
            "projects": {
                "submitted": solutions["submitted"],
                "awaiting_evaluation": solutions["awaiting_evaluation"],
                "partially_evaluated": solutions["partially_evaluated"],
                "evaluated": solutions["evaluated"],
            },
        },
        "attention": {
            "participants_without_team": participants["without_team"],
            "projects_awaiting_evaluation": projects_awaiting_evaluation,
            "delayed_experts": (
                build_delayed_experts(assignment_items)
                if program.is_distributed_evaluation
                else {"total": 0, "items": []}
            ),
        },
        "activity": _get_activity(program_id),
    }
