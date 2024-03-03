from django.contrib import admin
from django.contrib.contenttypes.admin import GenericStackedInline

from core.models import (
    Like,
    View,
    Link,
    Specialization,
    SpecializationCategory,
    Skill,
    SkillCategory,
    SkillToObject,
)


class SkillToObjectInline(GenericStackedInline):
    model = SkillToObject
    extra = 1
    verbose_name = "Навык"
    verbose_name_plural = "Навыки"


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "content_type", "object_id", "content_object")
    list_display_links = ("id", "user", "content_type", "object_id", "content_object")


@admin.register(View)
class ViewAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "content_type", "object_id", "content_object")
    list_display_links = ("id", "user", "content_type", "object_id", "content_object")


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("id", "link", "content_type", "object_id", "content_object")
    list_display_links = ("id", "link", "content_type", "object_id", "content_object")


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "category",
    )
    list_display_links = (
        "id",
        "name",
    )


@admin.register(SkillCategory)
class SkillCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
    )
    list_display_links = (
        "id",
        "name",
    )


@admin.register(Specialization)
class SpecializationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "category",
    )
    list_display_links = (
        "id",
        "name",
    )


@admin.register(SpecializationCategory)
class SpecializationCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
    )
    list_display_links = (
        "id",
        "name",
    )
