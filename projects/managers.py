from django.contrib.auth import get_user_model
from django.db.models import Manager

User = get_user_model()


class CollaboratorManager(Manager):
    def get_draft_projects_for_user(self):
        return (
            super()
            .get_queryset()
            .select_related("project")
            .filter(project__is_draft=True)
        )


class ProjectManager(Manager):
    def get_projects_for_list_view(self):
        return (
            self.get_queryset()
            .filter(draft=False)
            .prefetch_related("program_links__partner_program")
        )

    def get_user_projects_for_list_view(self):
        return (
            self.get_queryset()
            .prefetch_related("program_links__partner_program")
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
                "goals__responsible",
                "project_companies__company",
                "project_companies__decision_maker",
                "resources__partner_company",
            )
            .all()
        )

    def get_projects_for_count_view(self):
        return self.get_queryset().only("id", "leader_id")

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
