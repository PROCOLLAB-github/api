from django.contrib import admin
from .models import Criteria, ProjectScore


# Register your models here.
@admin.register(Criteria)
class CriteriaAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "type", "get_program_name")
    list_display_links = (
        "id",
        "name",
    )

    def get_program_name(self, obj):
        return obj.partner_program.name


@admin.register(ProjectScore)
class ProjectScoreAdmin(admin.ModelAdmin):
    list_display = ("id", "get_user_name", "get_project_name", "get_criteria_name")
    list_display_links = ("id",)

    def get_user_name(self, obj):
        return f"{obj.user.last_name} {obj.user.first_name}"

    def get_criteria_name(self, obj):
        return obj.criteria.name

    def get_project_name(self, obj):
        return obj.project.name
