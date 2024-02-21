from django.contrib import admin
from .models import Criteria, ProjectScore


# Register your models here.
@admin.register(Criteria)
class CriteriaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "type",
        # добавить проект / программу
    )
    list_display_links = (
        "id",
        "name",
    )


@admin.register(ProjectScore)
class ProjectScoreAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        # добавить проект / программу
    )
    list_display_links = ("id",)
