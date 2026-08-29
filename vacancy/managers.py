from datetime import timedelta

from django.db.models import Count, Manager, Prefetch, Q
from django.utils import timezone

from core.models import SkillToObject


class VacancyManager(Manager):
    def get_vacancy_for_list_view(self):
        expiration_check = timezone.now() - timedelta(days=90)
        return (
            self.get_queryset()
            .select_related("project")
            .prefetch_related(
                Prefetch(
                    "required_skills",
                    queryset=SkillToObject.objects.select_related(
                        "skill",
                        "skill__category",
                    ),
                )
            )
            .annotate(
                pending_response_count=Count(
                    "vacancy_requests",
                    filter=Q(vacancy_requests__is_approved__isnull=True),
                )
            )
            .filter(datetime_created__gte=expiration_check)
            .only(
                "role",
                "specialization",
                "description",
                "project__id",
                "project__name",
                "project__leader",
                "project__description",
                "project__image_address",
                "project__industry",
                "project__is_company",
                "project__draft",
                "project__is_public",
                "is_active",
                "datetime_closed",
                "datetime_created",
                "datetime_updated",
                "required_experience",
                "work_schedule",
                "work_format",
                "salary",
                "city",
            )
        )

    def get_vacancy_for_detail_view(self):
        return (
            self.get_queryset()
            .select_related("project", "project__industry")
            .prefetch_related("project__links")
            .only(
                "role",
                "required_skills",
                "description",
                "project",
                "project__name",
                "project__description",
                "project__image_address",
                "project__is_company",
                "project__industry",
                "project__links__link",
                "project__leader",
                "project__draft",
                "project__is_public",
                "is_active",
                "datetime_created",
                "datetime_updated",
            )
        )


class VacancyResponseManager(Manager):
    def get_vacancy_response_for_list_view(self):
        return self.get_queryset().select_related(
            "vacancy",
            "vacancy__project",
            "vacancy__project__leader",
            "accompanying_file",
        )

    def get_vacancy_response_for_email(self):
        return (
            self.get_queryset()
            .select_related(
                "user",
                "vacancy",
                "vacancy__project",
                "vacancy__project__leader",
                "accompanying_file",
            )
            .only(
                "user__id",
                "vacancy__id",
                "vacancy__project",
                "vacancy__project__leader__id",
                "why_me",
                "accompanying_file",
                "is_approved",
            )
        )

    def get_vacancy_response_for_detail_view(self):
        return (
            self.get_queryset()
            .select_related("user", "vacancy", "accompanying_file")
            .only(
                "user",
                "vacancy",
                "vacancy__role",
                "why_me",
                "accompanying_file",
                "is_approved",
                "datetime_created",
                "datetime_updated",
            )
        )
