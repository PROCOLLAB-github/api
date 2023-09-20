from django.contrib import admin

from projects.models import (
    DefaultProjectCover,
    Project,
    Achievement,
    Collaborator,
    ProjectLink,
    ProjectNews,
)


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


@admin.register(ProjectNews)
class ProjectNewsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "datetime_created",
    )
    list_display_links = (
        "id",
        "project",
        "datetime_created",
    )
    # todo: set up admin panel for files
    filter_horizontal = ("files",)


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "project")


@admin.register(ProjectLink)
class ProjectLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "link", "project")
    list_display_links = ("id", "link", "project")


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


@admin.register(DefaultProjectCover)
class DefaultProjectCoverAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "image",
        "datetime_created",
        "datetime_updated",
    )
    list_display_links = (
        "id",
        "datetime_created",
        "datetime_updated",
    )
