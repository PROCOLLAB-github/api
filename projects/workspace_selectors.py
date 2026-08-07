from django.db.models import Count, Prefetch, Q, QuerySet

from core.models import SkillToObject
from partner_programs.models import Application
from projects.models import Collaborator, Project
from vacancy.models import Vacancy


def _with_workspace_relations(queryset: QuerySet[Project], user) -> QuerySet[Project]:
    """Загружает роли и активности заранее, исключая N+1 в API проектов."""
    current_user_collaborations = Collaborator.objects.filter(user=user)
    applications = Application.objects.select_related("program").order_by(
        "-updated_at", "-id"
    )
    return queryset.select_related("leader", "industry").prefetch_related(
        Prefetch(
            "collaborator_set",
            queryset=current_user_collaborations,
            to_attr="_current_user_collaborations",
        ),
        Prefetch(
            "applications",
            queryset=applications,
            to_attr="_workspace_applications",
        ),
    )


def get_project_catalog_queryset(*, user, search=None, industry_id=None):
    """Возвращает опубликованные публичные проекты в стабильном порядке."""
    queryset = Project.objects.filter(draft=False, is_public=True)
    if search:
        queryset = queryset.filter(name__icontains=search.strip())
    if industry_id:
        queryset = queryset.filter(industry_id=industry_id)
    return _with_workspace_relations(queryset, user).order_by("-datetime_updated", "-id")


def get_user_projects_queryset(*, user, search=None):
    """Возвращает проекты пользователя как руководителя или участника."""
    queryset = Project.objects.filter(
        Q(leader=user) | Q(collaborator__user=user)
    ).distinct()
    if search:
        queryset = queryset.filter(name__icontains=search.strip())
    return _with_workspace_relations(queryset, user).order_by("-datetime_updated", "-id")


def get_workspace_project_queryset(*, user):
    """Готовит detail queryset с безопасными пользовательскими связями проекта."""
    collaborators = Collaborator.objects.select_related("user").order_by(
        "datetime_created", "id"
    )
    required_skills = SkillToObject.objects.select_related("skill__category")
    vacancies = (
        Vacancy.objects.annotate(
            workspace_response_count=Count(
                "vacancy_requests",
                filter=Q(vacancy_requests__is_approved__isnull=True),
            )
        )
        .prefetch_related(Prefetch("required_skills", queryset=required_skills))
        .order_by("-datetime_created", "-id")
    )
    queryset = _with_workspace_relations(Project.objects.all(), user)
    return queryset.prefetch_related(
        Prefetch(
            "collaborator_set",
            queryset=collaborators,
            to_attr="_workspace_collaborators",
        ),
        "links",
        Prefetch("vacancies", queryset=vacancies),
    )


def filter_workspace_visible_projects(queryset: QuerySet[Project], *, user):
    """Ограничивает queryset действующими правилами видимости workspace."""
    if user.is_staff or user.is_superuser:
        return queryset
    return queryset.filter(
        Q(draft=False, is_public=True) | Q(leader=user) | Q(collaborator__user=user)
    ).distinct()
