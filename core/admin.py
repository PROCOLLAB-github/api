from django.contrib import admin
from core.models import Like


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "content_type", "object_id", "content_object")
    list_display_links = ("id", "user", "content_type", "object_id", "content_object")
