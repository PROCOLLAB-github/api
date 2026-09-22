from django.contrib.auth import get_user_model
from django.db.models import Count, Manager, OuterRef, Q, Subquery

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
            .filter(draft=False, is_public=True)
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

    def get_user_activity_counts(self, user):
        """Считает проектную активность пользователя одним SQL-запросом.

        Для lifecycle используется первая legacy-связь с программой по минимальному
        ``PartnerProgramProject.pk`` — тот же canonical link, который возвращают
        карточки и detail проекта. Агрегация выполняется на backend, потому что
        dashboard загружает только первые 16 проектов пользователя.
        """
        from partner_programs.models import PartnerProgramProject

        canonical_program_link = PartnerProgramProject.objects.filter(
            project_id=OuterRef("pk")
        ).order_by("pk")
        user_projects = Q(leader_id=user.id) | Q(collaborator__user_id=user.id)

        return (
            self.get_queryset()
            .annotate(
                canonical_program_link_id=Subquery(
                    canonical_program_link.values("pk")[:1]
                ),
                canonical_program_link_submitted=Subquery(
                    canonical_program_link.values("submitted")[:1]
                ),
            )
            .aggregate(
                all=Count(
                    "pk",
                    filter=Q(draft=False, is_public=True),
                    distinct=True,
                ),
                my=Count("pk", filter=user_projects, distinct=True),
                my_leader=Count("pk", filter=Q(leader_id=user.id), distinct=True),
                my_in_program=Count(
                    "pk",
                    filter=(
                        user_projects
                        & Q(canonical_program_link_id__isnull=False)
                        & Q(canonical_program_link_submitted=False)
                        & Q(draft=False)
                    ),
                    distinct=True,
                ),
                my_submitted=Count(
                    "pk",
                    filter=user_projects & Q(canonical_program_link_submitted=True),
                    distinct=True,
                ),
            )
        )

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
