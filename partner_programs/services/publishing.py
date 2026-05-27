from django.utils import timezone

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from projects.models import Project


def publish_finished_program_projects(now=None) -> int:
    if now is None:
        now = timezone.now()

    program_ids = PartnerProgram.objects.filter(
        publish_projects_after_finish=True,
        datetime_finished__lte=now,
    ).values_list("id", flat=True)
    if not program_ids.exists():
        return 0

    link_project_ids = PartnerProgramProject.objects.filter(
        partner_program_id__in=program_ids
    ).values_list("project_id", flat=True)
    profile_project_ids = PartnerProgramUserProfile.objects.filter(
        partner_program_id__in=program_ids,
        project_id__isnull=False,
    ).values_list("project_id", flat=True)
    project_ids = link_project_ids.union(profile_project_ids)

    return Project.objects.filter(
        id__in=project_ids,
        is_public=False,
        draft=False,
    ).update(is_public=True)
