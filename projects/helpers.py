from random import sample

from django.contrib.auth import get_user_model


from partner_programs.models import (
    PartnerProgramUserProfile,
)
from projects.models import Project, ProjectLink, Achievement

User = get_user_model()


def get_recommended_users(project: Project, *, program_link_id=None) -> list[User]:
    """
    Searches for users by matching their skills and vacancies required_skills
    """
    RECOMMENDATIONS_COUNT = 5
    all_needed_skills = set()
    for vacancy in project.vacancies.all():
        all_needed_skills.update(set(vacancy.get_required_skills()))

    recommended_users = []
    from projects.team_policy import actionable_users

    candidates = actionable_users(
        project, User.objects.get_members(), program_link_id=program_link_id
    )
    for user in candidates:
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


def update_partner_program(program_id, user, instance, program_link_id=None):
    from projects.team_service import bind_project_to_program

    return bind_project_to_program(
        project_id=instance.pk,
        program_id=program_id,
        actor=user,
        program_link_id=program_link_id,
    )


def clear_project_existing_from_profile(user, instance) -> None | int:
    """Remove project from `PartnerProgramUserProfile` instance."""
    existing_program_profile = (
        PartnerProgramUserProfile.objects.select_related("partner_program")
        .filter(user=user, project=instance)
        .first()
    )
    if existing_program_profile:
        existing_program_profile.project = None
        existing_program_profile.save()
        return existing_program_profile.partner_program.id
