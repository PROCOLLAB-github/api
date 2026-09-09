"""Project-level involvement and program-scoped read access."""

from django.db.models import Q

from partner_programs.models import PartnerProgramProject
from projects.models import Project


def has_project_level_read_access(user, project: Project) -> bool:
    """Existing project/admin involvement, independent of any program role."""
    if not user or not user.is_authenticated:
        return False
    return (
        user.is_staff
        or user.is_superuser
        or project.leader_id == user.pk
        or project.collaborator_set.filter(user_id=user.pk).exists()
        or project.invite_set.filter(user_id=user.pk).exists()
    )


def program_role_project_links(user, project: Project):
    """Only links whose program the user manages or evaluates; no per-link SQL."""
    if not user or not user.is_authenticated:
        return PartnerProgramProject.objects.none()
    return project.program_links.filter(
        Q(partner_program__managers__pk=user.pk)
        | Q(partner_program__experts__user_id=user.pk)
    )


def has_project_read_involvement(user, project: Project) -> bool:
    """Read-only grant; callers must keep existing write permissions separate."""
    return (
        has_project_level_read_access(user, project)
        or program_role_project_links(user, project).exists()
    )


def has_program_link_read_access(user, link: PartnerProgramProject) -> bool:
    """Read this link's fields, never another program via shared Project access."""
    return (
        has_project_level_read_access(user, link.project)
        or program_role_project_links(user, link.project).filter(pk=link.pk).exists()
    )
