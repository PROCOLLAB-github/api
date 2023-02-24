from django.db.models import Manager
from django.db.models import Prefetch

from industries.models import Industry
from users.models import CustomUser


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
                # Prefetch(
                #     "collaborator_set",
                #     queryset=Collaborator.objects.filter(
                #         id__in=Subquery(
                #              Collaborator.objects
                #              .filter(project_id=OuterRef('project_id')).values_list('id', flat=True)[:4]
                #         )
                #     ),
                #     to_attr='collaborators'
                # ),
                # Yes, this fetches the entire collaborator_set even though we only need 4 and the total count.
                # No, You can't do it any other way than this.
                # Above is a hack that can fetch max 4 vacancies, but if you use it the count will always be <=4.
                # To get the count right using the thing above you either have to make another godawful hack,
                # Or override the default QuerySet to always ask the DB only count after all the filters.
                # (ticket referring to the reason why you can't
                # prefetch N items easily https://code.djangoproject.com/ticket/26780)
                # (seems like in django 4.2.0 it'll be fixed but at the time of writing the latest version is 4.1.3
                Prefetch("collaborator_set"),
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
            self.get_queryset().prefetch_related("achievements", "collaborator_set").all()
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
