from django.contrib import admin

from projects.models import Project, Achievement, Collaborator


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "draft",
    )
    list_display_links = (
        "id",
        "name",
    )


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "project")


@admin.register(Collaborator)
class CollaboratorAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "project",
        "role",
        "datetime_created",
        "datetime_updated",
    )
    list_display_links = ("id", "user", "project")
