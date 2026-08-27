from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet

from core.models import SkillToObject
from projects.models import Collaborator, Project
from vacancy.models import Vacancy, VacancyResponse


def _skill_relations_queryset() -> QuerySet[SkillToObject]:
    return SkillToObject.objects.select_related("skill", "skill__category")


def _response_vacancies_queryset() -> QuerySet[Vacancy]:
    return (
        Vacancy.objects.select_related("project", "project__industry")
        .prefetch_related(
            Prefetch(
                "required_skills",
                queryset=_skill_relations_queryset(),
            ),
            "project__links",
        )
        .annotate(
            pending_response_count=Count(
                "vacancy_requests",
                filter=Q(vacancy_requests__is_approved__isnull=True),
            )
        )
    )


def get_response_queryset() -> QuerySet[VacancyResponse]:
    """Загружает manager response contract без запросов на каждого кандидата."""

    return (
        VacancyResponse.objects.select_related(
            "user",
            "user__v2_speciality",
            "user__v2_speciality__category",
            "vacancy",
            "vacancy__project",
            "vacancy__project__leader",
            "accompanying_file",
        )
        .prefetch_related(
            Prefetch(
                "user__skills",
                queryset=_skill_relations_queryset(),
            )
        )
        .order_by("datetime_created", "id")
    )


def get_self_response_queryset() -> QuerySet[VacancyResponse]:
    """Загружает собственные отклики вместе с безопасной карточкой вакансии."""

    return (
        VacancyResponse.objects.select_related("accompanying_file")
        .prefetch_related(
            Prefetch("vacancy", queryset=_response_vacancies_queryset()),
        )
        .order_by("datetime_created", "id")
    )


def with_applicant_state(queryset: QuerySet[Vacancy], user) -> QuerySet[Vacancy]:
    """Добавляет UI-hints одним SQL-запросом, не превращая их в границу доступа."""

    if not user or not user.is_authenticated:
        return queryset
    return queryset.annotate(
        current_user_has_responded=Exists(
            VacancyResponse.objects.filter(
                vacancy_id=OuterRef("pk"),
                user_id=user.id,
            )
        ),
        current_user_is_collaborator=Exists(
            Collaborator.objects.filter(
                project_id=OuterRef("project_id"),
                user_id=user.id,
            )
        ),
    )


def can_manage_project(user, project: Project) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (
            project.leader_id == user.id
            or getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
        )
    )


def can_manage_vacancy(user, vacancy: Vacancy) -> bool:
    return can_manage_project(user, vacancy.project)
