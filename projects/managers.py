from django.db.models import Manager
from django.db.models import Prefetch

from industries.models import Industry
from users.models import CustomUser


class ProjectManager(Manager):
    def get_projects_for_list_view(self):
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
            )
            .only(
                "id",
                "name",
                "leader__id",
                "description",
                "short_description",
                "step",
                "industry__name",
                "image_address",
                "draft",
                "datetime_created",
            )
            .all()
        )

    def get_projects_for_detail_view(self):
        return (
            self.get_queryset()
            .prefetch_related(
                "collaborators",
                "achievements",
            )
            .all()
        )

    def check_if_owns_any_projects(self, user) -> bool:
        return user.leader_projects.exists()


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
