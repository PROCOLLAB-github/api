"""Принятая команда решения; анкета и ожидающее приглашение не доказывают членство."""

from django.db.models import Case, Value, When

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.solution_models import ProgramSolution, ProgramSolutionMember


def uses_solutions(program_id):
    return PartnerProgram.objects.filter(
        pk=program_id, solution_storage_mode="solution"
    ).exists()


def membership_user_ids(program_id):
    captains = ProgramSolution.objects.filter(program_id=program_id).order_by()
    members = ProgramSolutionMember.objects.filter(
        solution__program_id=program_id,
        solution__archived_at__isnull=True,
    ).order_by()
    # Сохраняем internal aliases прежней SQL-проекции для общих счетчиков и списков.
    return dict(
        is_project_leader=captains.values("captain_id"),
        is_submitted_project_leader=captains.filter(status="submitted").values(
            "captain_id"
        ),
        is_project_collaborator=members.values("user_id"),
    )


def matches_membership(users):
    return Case(When(user_id__in=users, then=Value(True)), default=Value(False))


def participant_profiles(program_id, profiles=None):
    if profiles is None:
        profiles = PartnerProgramUserProfile.objects.filter(partner_program_id=program_id)
    return profiles.annotate(
        **{
            key: matches_membership(users)
            for key, users in membership_user_ids(program_id).items()
        }
    )
