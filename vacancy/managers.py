from django.db.models import Manager


class VacancyManager(Manager):
    def get_vacancy_for_list_view(self):
        return (
            self.get_queryset()
            .select_related("project")
            .only(
                "role",
                "required_skills",
                "description",
                "project__id",
                "is_active",
            )
        )

    def get_vacancy_for_detail_view(self):
        return (
            self.get_queryset()
            .select_related("project")
            .only(
                "role",
                "required_skills",
                "description",
                "project",
                "is_active",
                "datetime_created",
                "datetime_updated",
            )
        )


class VacancyResponseManager(Manager):
    def get_vacancy_response_for_list_view(self):
        return (
            self.get_queryset()
            .select_related("user", "vacancy", "accompanying_file")
            .only(
                "user__id",
                "vacancy__id",
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
                "why_me",
                "accompanying_file",
                "is_approved",
                "datetime_created",
                "datetime_updated",
            )
        )
