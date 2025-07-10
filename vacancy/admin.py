import tablib
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path

from core.admin import SkillToObjectInline
from vacancy.models import Vacancy, VacancyResponse


class VacancySkillToObjectInline(SkillToObjectInline):
    verbose_name_plural = "Необходимые навыки"


@admin.register(Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = [
        "role",
        "specialization",
        "description",
        "project",
        "is_active",
        "datetime_created",
        "datetime_updated",
    ]
    inlines = [
        VacancySkillToObjectInline,
    ]
    readonly_fields = ("datetime_closed",)
    list_display_links = ["role"]

    change_list_template = "vacancies/vacancies_change_list.html"

    def get_urls(self):
        default_urls = super(VacancyAdmin, self).get_urls()
        custom_urls = [
            path(
                "email-vacancies/",
                self.admin_site.admin_view(self.email_leaders_vacancies),
                name="vacancy_leaders_email",
            )
        ]
        return custom_urls + default_urls

    def email_leaders_vacancies(self, request):
        data = list(
            Vacancy.objects.select_related("project", "project__leader").values_list(
                "project__leader__email", "datetime_created", "project__id", "role"
            )
        )
        return self.excel_email_leaders_vacancies(data)

    def excel_email_leaders_vacancies(self, data: list):
        response_data = tablib.Dataset(
            headers=["email", "дата", "ссылка на проект", "название вакансии"]
        )

        for row in data:
            row_to_add = [
                row[0],
                row[1].strftime("%d-%m-%Y %S:%M:%H %Z"),
                f"https://app.procollab.ru/office/projects/{row[2]}",
                row[3],
            ]
            response_data.append(row_to_add)

        binary_data = response_data.export("xlsx")
        file_name = "email_of_leaders_with_users"
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{file_name}.xlsx"'},
        )
        response.write(binary_data)
        return response


@admin.register(VacancyResponse)
class VacancyResponseAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "vacancy",
        "why_me",
        "is_approved",
        "datetime_created",
        "datetime_updated",
    ]
