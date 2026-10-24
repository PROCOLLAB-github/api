"""Принятая команда решения; анкета и ожидающее приглашение не доказывают членство."""

from django.db.models import Exists, OuterRef

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.solution_models import ProgramSolution, ProgramSolutionMember


def uses_solutions(program_id):
    return PartnerProgram.objects.filter(
        pk=program_id, solution_storage_mode="solution"
    ).exists()


def membership_expressions(program_id):
    captains = ProgramSolution.objects.filter(
        program_id=program_id, captain_id=OuterRef("user_id")
    )
    members = ProgramSolutionMember.objects.filter(
        solution__program_id=program_id, user_id=OuterRef("user_id")
    )
    # Сохраняем internal aliases прежней SQL-проекции для общих счетчиков и списков.
    return dict(
        is_project_leader=Exists(captains),
        is_submitted_project_leader=Exists(captains.filter(status="submitted")),
        is_project_collaborator=Exists(members),
    )


def participant_profiles(program_id, profiles=None):
    if profiles is None:
        profiles = PartnerProgramUserProfile.objects.filter(partner_program_id=program_id)
    return profiles.annotate(**membership_expressions(program_id))
