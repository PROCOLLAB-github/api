from django.contrib import admin

from core.admin import SkillToObjectInline
from vacancy.models import Vacancy, VacancyResponse


class VacancySkillToObjectInline(SkillToObjectInline):
    verbose_name_plural = "Необходимые навыки"


@admin.register(Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = [
        "role",
        "description",
        "project",
        "is_active",
        "datetime_created",
        "datetime_updated",
    ]
    inlines = [
        VacancySkillToObjectInline,
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
