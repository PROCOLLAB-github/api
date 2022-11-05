from django.db.models import Manager
from django.db.models import Prefetch

from industries.models import Industry
from users.models import CustomUser


class ProjectManager(Manager):
    def get_projects_for_list_view(self):
        return self.get_queryset().prefetch_related(
            Prefetch(
                "industry",
                queryset=Industry.objects.only("name").all(),
            ),
            Prefetch(
                "leader",
                queryset=CustomUser.objects.only("id").all(),
            ),
            # способ выбрать N объектов из prefetch
            # БЛЯТЬ СУКА КАКОЙ ЕБАНЫЙ ПИЗДЕЦ НАХУЙ ГОВНОКОДИЩЕ БЛЯТЬ
            # кажется единственный нормальный способ это сделать будет только в 4.2.0
            # тикет https://code.djangoproject.com/ticket/26780
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
            Prefetch("collaborator_set", to_attr="collaborators"),
        )

    def get_projects_for_detail_view(self):
        return (
            self.get_queryset().prefetch_related("achievements", "collaborator_set").all()
        )

    def check_if_owns_any_projects(self, user) -> bool:
        # I don't think this should work but the function has no usages, so I'll let it be
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
