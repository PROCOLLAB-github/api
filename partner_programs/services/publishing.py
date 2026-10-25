from django.utils import timezone
from django.db import transaction

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from projects.models import Project
from partner_programs.solution_models import ProgramSolution


def publish_finished_program_projects(now=None) -> int:
    if now is None:
        now = timezone.now()

    program_ids = PartnerProgram.objects.filter(
        solution_storage_mode="legacy_project",
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


def solution_publication_filter(now):
    return dict(
        solution_storage_mode="solution",
        is_competitive=False,
        publish_projects_after_finish=True,
        datetime_finished__lte=now,
    )


@transaction.atomic
def publish_solution_program(program_id, *, now):
    program = (
        PartnerProgram.objects.select_for_update()
        .filter(pk=program_id, **solution_publication_filter(now))
        .first()
    )
    if program is None:
        return 0
    return ProgramSolution.objects.filter(
        program=program, published_at__isnull=True
    ).update(published_at=now)


def publish_finished_program_solutions(now=None) -> int:
    now = timezone.now() if now is None else now
    program_ids = (
        PartnerProgram.objects.filter(**solution_publication_filter(now))
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    return sum(
        publish_solution_program(program_id, now=now)
        for program_id in program_ids.iterator()
    )
