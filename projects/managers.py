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
        # users = CustomUser.objects.only("id").all()
        return (
            self.get_queryset()
            .prefetch_related(
                # Prefetch(
                #     "industry",
                #     queryset=Industry.objects.only("name").all(),
                # ),
                # Prefetch(
                #     "leader",
                #     queryset=users,
                # ),
                "collaborators",
                "achievements",
            )
            .all()
        )
