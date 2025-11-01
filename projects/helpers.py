from random import sample

from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from rest_framework.exceptions import ValidationError

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from projects.models import Project, ProjectLink, Achievement
from users.models import CustomUser

User = get_user_model()


def get_recommended_users(project: Project) -> list[User]:
    """
    Searches for users by matching their skills and vacancies required_skills
    """
    RECOMMENDATIONS_COUNT = 5
    all_needed_skills = set()
    for vacancy in project.vacancies.all():
        all_needed_skills.update(set(vacancy.get_required_skills()))

    recommended_users = []
    for user in User.objects.get_members():
        if user == project.leader or user.skills_count < 1:
            continue

        user_skills = set(user.get_skills())

        if all_needed_skills & user_skills:
            recommended_users.append(user)

    # get some random users
    sampled_recommended_users = sample(
        recommended_users, min(RECOMMENDATIONS_COUNT, len(recommended_users))
    )

    return sampled_recommended_users


def check_related_fields_update(data, pk):
    """
    Check if achievements or links were updated and update them.
    """

    if data.get("achievements") is not None:
        update_achievements(data.get("achievements"), pk)

    if data.get("links") is not None:
        update_links(data.get("links"), pk)


def update_achievements(achievements, pk):
    """
    Bootleg version of updating achievements via project
    """

    # delete all old achievements
    Achievement.objects.filter(project_id=pk).delete()
    # create new achievements
    Achievement.objects.bulk_create(
        [
            Achievement(
                project_id=pk,
                title=achievement.get("title"),
                status=achievement.get("status"),
            )
            for achievement in achievements
        ]
    )


def update_links(links, pk):
    """
    Bootleg version of updating links via project
    """

    # delete all old links
    ProjectLink.objects.filter(project_id=pk).delete()
    # create new links
    ProjectLink.objects.bulk_create(
        [
            ProjectLink(
                project_id=pk,
                link=link,
            )
            for link in links
        ]
    )


@transaction.atomic
def update_partner_program(
    program_id: int,
    user: CustomUser,
    instance: Project,
) -> None:
    """
    According to the current logic, 1 user project can be linked to only 1 program.
    The user cannot select a ready program, but can edit a project with a ready program
    (if the time period allows access).
    If he changes the program (completed), he will not be able to return it.
    """
    if program_id is not None:
        # If the user removes the tag, frontend sends `int -> 0` (id == 0 cannot exist).
        if program_id == 0:
            clear_project_existing_from_profile(user, instance)
        else:
            partner_program = PartnerProgram.objects.get(pk=program_id)
            existing_program_id: int | None = clear_project_existing_from_profile(user, instance)

            if (
                partner_program.datetime_finished < timezone.now()
                and (existing_program_id != program_id)
            ):
                raise ValidationError({"error": "Cannot select a completed program."})

            partner_program_profile = PartnerProgramUserProfile.objects.get(
                user=user,
                partner_program=partner_program,
            )
            partner_program_profile.project = instance
            partner_program_profile.save()


def clear_project_existing_from_profile(user, instance) -> None | int:
    """Remove project from `PartnerProgramUserProfile` instance."""
    existing_program_profile = (
        PartnerProgramUserProfile.objects
        .select_related("partner_program")
        .filter(user=user, project=instance)
        .first()
    )
    if existing_program_profile:
        existing_program_profile.project = None
        existing_program_profile.save()
        return existing_program_profile.partner_program.id
