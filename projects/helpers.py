from random import sample

from django.contrib.auth import get_user_model

from projects.constants import RECOMMENDATIONS_COUNT
from projects.models import Project

User = get_user_model()


def get_recommended_users(project: Project) -> list[User]:
    """
    Searches for users by matching their key_skills and vacancies required_skills
    """

    # fixme: store key_skills and required_skills more convenient, not just as a string
    all_needed_skills = set()
    for vacancy in project.vacancies.all():
        all_needed_skills.update(set(vacancy.required_skills.lower().split(",")))

    recommended_users = []
    for user in User.objects.get_members():
        if user == project.leader or not user.key_skills:
            continue

        skills = set(user.key_skills.lower().split(","))
        if skills.intersection(all_needed_skills):
            recommended_users.append(user)

    # get some random users
    sampled_recommended_users = sample(
        recommended_users, min(RECOMMENDATIONS_COUNT, len(recommended_users))
    )

    return sampled_recommended_users
