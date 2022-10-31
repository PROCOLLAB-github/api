from django.contrib import admin

from vacancy.models import Vacancy, VacancyResponse


@admin.register(Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = [
        "role",
        "required_skills",
        "description",
        "project",
        "is_active",
        "datetime_created",
        "datetime_updated",
    ]
    list_display_links = ["role"]


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
