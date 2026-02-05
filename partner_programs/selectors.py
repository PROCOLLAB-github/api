from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from projects.models import Collaborator

User = get_user_model()


def programs_with_submission_deadline_on(target_date):
    return PartnerProgram.objects.filter(
        Q(datetime_project_submission_ends__date=target_date)
        | Q(
            datetime_project_submission_ends__isnull=True,
            datetime_registration_ends__date=target_date,
        )
    )


def programs_with_registrations_on(target_date):
    return PartnerProgram.objects.filter(
        partner_program_profiles__datetime_created__date=target_date
    ).distinct()


def _participant_profiles(program_id: int):
    return PartnerProgramUserProfile.objects.filter(
        partner_program_id=program_id, user__isnull=False
    )


def program_participants(program_id: int):
    user_ids = _participant_profiles(program_id).values_list("user_id", flat=True)
    return User.objects.filter(id__in=user_ids).distinct()


def program_participants_without_project(program_id: int):
    profiles = _participant_profiles(program_id)
    leader_exists = Exists(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            project__leader_id=OuterRef("user_id"),
        )
    )
    collab_exists = Exists(
        Collaborator.objects.filter(
            user_id=OuterRef("user_id"),
            project__program_links__partner_program_id=program_id,
        )
    )
    eligible_ids = (
        profiles.annotate(is_leader=leader_exists, is_collab=collab_exists)
        .filter(is_leader=False, is_collab=False)
        .values_list("user_id", flat=True)
    )
    return User.objects.filter(id__in=eligible_ids).distinct()


def program_participants_without_project_registered_on(program_id: int, target_date):
    profiles = _participant_profiles(program_id).filter(
        datetime_created__date=target_date
    )
    leader_exists = Exists(
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id,
            project__leader_id=OuterRef("user_id"),
        )
    )
    collab_exists = Exists(
        Collaborator.objects.filter(
            user_id=OuterRef("user_id"),
            project__program_links__partner_program_id=program_id,
        )
    )
    eligible_ids = (
        profiles.annotate(is_leader=leader_exists, is_collab=collab_exists)
        .filter(is_leader=False, is_collab=False)
        .values_list("user_id", flat=True)
    )
    return User.objects.filter(id__in=eligible_ids).distinct()


def program_participants_with_unsubmitted_project(program_id: int):
    participant_ids = _participant_profiles(program_id).values_list(
        "user_id", flat=True
    )
    leader_ids = PartnerProgramProject.objects.filter(
        partner_program_id=program_id, submitted=False
    ).values_list("project__leader_id", flat=True)
    collab_ids = Collaborator.objects.filter(
        project__program_links__partner_program_id=program_id,
        project__program_links__submitted=False,
    ).values_list("user_id", flat=True)
    return User.objects.filter(id__in=participant_ids).filter(
        Q(id__in=leader_ids) | Q(id__in=collab_ids)
    ).distinct()
