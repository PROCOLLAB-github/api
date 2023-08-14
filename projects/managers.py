from django.contrib.auth import get_user_model
from django.db.models import Manager
from django.db.models import Prefetch

from industries.models import Industry
from users.models import CustomUser

User = get_user_model()


class ProjectManager(Manager):
    def get_projects_for_list_view(self):
        return (
            self.get_queryset()
            .filter(draft=False)
            .prefetch_related(
                Prefetch(
                    "industry",
                    queryset=Industry.objects.only("name").all(),
                ),
                Prefetch(
                    "leader",
                    queryset=CustomUser.objects.only("id").all(),
                ),
                "partner_program_profiles",
            )
        )

    def get_user_projects_for_list_view(self):
        return (
            self.get_queryset()
            .prefetch_related(
                Prefetch(
                    "industry",
                    queryset=Industry.objects.only("name").all(),
                ),
                Prefetch(
                    "leader",
                    queryset=CustomUser.objects.only("id").all(),
                ),
                Prefetch("collaborator_set"),
            )
            .distinct()
        )

    def get_projects_for_detail_view(self):
        return (
            self.get_queryset()
            .prefetch_related(
                "achievements",
                "collaborator_set",
                "vacancies",
                "links",
            )
            .all()
        )

    def get_projects_for_count_view(self):
        return self.get_queryset().only("id", "leader_id")

    def check_if_owns_any_projects(self, user) -> bool:
        # I don't think this should work but the function has no usages, so I'll let it be
        return user.leader_projects.exists()

    def get_projects_from_list_of_ids(self, ids):
        return self.get_queryset().filter(id__in=ids)


class AchievementManager(Manager):
    def get_achievements_for_list_view(self):
        return (
            self.get_queryset()
            .select_related("project")
            .only("id", "title", "status", "project__id")
        )

    def get_achievements_for_detail_view(self):
        return (
            self.get_queryset()
            .select_related("project")
            .only("id", "title", "status", "project")
        )
