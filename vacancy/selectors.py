from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet

from core.models import SkillToObject
from projects.models import Collaborator, Project
from users.public_profile_selectors import get_public_profiles_queryset
from vacancy.models import Vacancy, VacancyResponse


def _vacancy_queryset() -> QuerySet[Vacancy]:
    skills = SkillToObject.objects.select_related("skill", "skill__category")
    return (
        Vacancy.objects.select_related(
            "project",
            "project__industry",
        )
        .prefetch_related(
            Prefetch("required_skills", queryset=skills),
            "project__links",
        )
        .annotate(
            pending_response_count=Count(
                "vacancy_requests",
                filter=Q(vacancy_requests__is_approved__isnull=True),
            )
        )
    )


def get_public_vacancies_queryset() -> QuerySet[Vacancy]:
    """Возвращает только активные вакансии опубликованных публичных проектов."""

    return (
        _vacancy_queryset()
        .filter(
            is_active=True,
            project__draft=False,
            project__is_public=True,
        )
        .order_by("-datetime_created", "-id")
    )


def get_vacancy_queryset() -> QuerySet[Vacancy]:
    return _vacancy_queryset().order_by("-datetime_created", "-id")


def get_response_queryset() -> QuerySet[VacancyResponse]:
    candidate_profiles = get_public_profiles_queryset()
    return (
        VacancyResponse.objects.select_related(
            "vacancy",
            "vacancy__project",
            "accompanying_file",
        )
        .prefetch_related(Prefetch("user", queryset=candidate_profiles))
        .order_by("datetime_created", "id")
    )


def get_self_response_queryset() -> QuerySet[VacancyResponse]:
    """Загружает отклики пользователя вместе с карточками вакансий без N+1."""

    return (
        VacancyResponse.objects.select_related("accompanying_file")
        .prefetch_related(
            Prefetch("vacancy", queryset=_vacancy_queryset()),
        )
        .order_by("datetime_created", "id")
    )


def with_applicant_state(queryset: QuerySet[Vacancy], user) -> QuerySet[Vacancy]:
    """Добавляет UI-подсказки одним запросом, не заменяя серверную проверку POST."""

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


def is_staff(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    )


def can_manage_project(user, project: Project) -> bool:
    return is_staff(user) or (
        bool(user and user.is_authenticated) and project.leader_id == user.id
    )


def can_manage_vacancy(user, vacancy: Vacancy) -> bool:
    return can_manage_project(user, vacancy.project)


def can_view_vacancy(user, vacancy: Vacancy) -> bool:
    return can_manage_vacancy(user, vacancy) or (
        vacancy.is_active and not vacancy.project.draft and vacancy.project.is_public
    )
