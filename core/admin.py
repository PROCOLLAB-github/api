from django.contrib import admin
from core.models import Like, View, Link


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
