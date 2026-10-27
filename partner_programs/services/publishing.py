"""Publish eligible work on access; periodic tasks also repair publication markers."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramUserProfile,
)
from projects.models import Project
from partner_programs.solution_models import ProgramSolution


def publication_filter(now, mode):
    return dict(
        draft=False,
        solution_storage_mode=mode,
        publish_projects_after_finish=True,
        datetime_finished__lte=now,
    )


def legacy_program_projects(program_id):
    return Project.objects.filter(
        Q(program_links__partner_program_id=program_id)
        | Q(
            pk__in=PartnerProgramUserProfile.objects.filter(
                partner_program_id=program_id,
            ).values("project_id")
        ),
        draft=False,
        is_public=False,
    )


@transaction.atomic
def publish_legacy_program(program_id, *, now):
    program = (
        PartnerProgram.objects.select_for_update()
        .filter(pk=program_id, **publication_filter(now, "legacy_project"))
        .first()
    )
    if program is None:
        return 0
    return legacy_program_projects(program_id).update(is_public=True)


def solution_publication_filter(now):
    return publication_filter(now, "solution")


def unpublished_solutions(program):
    solutions = ProgramSolution.objects.filter(program=program, published_at__isnull=True)
    if program.is_competitive:
        # Несданные конкурсные черновики остаются закрытыми.
        solutions = solutions.filter(status="submitted")
    return solutions


@transaction.atomic
def publish_solution_program(program_id, *, now):
    program = (
        PartnerProgram.objects.select_for_update()
        .filter(pk=program_id, **solution_publication_filter(now))
        .first()
    )
    if program is None:
        return 0
    return unpublished_solutions(program).update(published_at=now)


def publish_program_if_due(program, *, now=None):
    """Recheck eligibility under the program lock, without waiting for cron.

    Closed programs and repeat reads avoid the lock/write. Only server publication
    markers change; existing markers are never revoked.
    """
    now = timezone.now() if now is None else now
    if (
        program.draft
        or not program.publish_projects_after_finish
        or program.datetime_finished > now
    ):
        return 0
    if program.solution_storage_mode == "solution":
        if not unpublished_solutions(program).exists():
            return 0
        return publish_solution_program(program.pk, now=now)
    if not legacy_program_projects(program.pk).exists():
        return 0
    return publish_legacy_program(program.pk, now=now)


def publish_project_if_due(project_id):
    """Direct legacy links work without visiting the program first."""
    now = timezone.now()
    programs = PartnerProgram.objects.filter(
        Q(program_projects__project_id=project_id)
        | Q(
            pk__in=PartnerProgramUserProfile.objects.filter(
                project_id=project_id,
            ).values("partner_program_id")
        ),
        **publication_filter(now, "legacy_project"),
    ).distinct().order_by("pk")
    return sum(publish_program_if_due(program, now=now) for program in programs)


def publish_finished_program_projects(now=None) -> int:
    now = timezone.now() if now is None else now
    programs = PartnerProgram.objects.filter(
        **publication_filter(now, "legacy_project")
    ).order_by("pk")
    return sum(publish_program_if_due(program, now=now) for program in programs.iterator())


def publish_finished_program_solutions(now=None) -> int:
    now = timezone.now() if now is None else now
    programs = (
        PartnerProgram.objects.filter(**solution_publication_filter(now))
        .order_by("pk")
    )
    return sum(
        publish_program_if_due(program, now=now) for program in programs.iterator()
    )
