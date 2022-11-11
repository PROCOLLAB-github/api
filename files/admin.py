from django.contrib import admin

from files.models import UserFile


@admin.register(UserFile)
class UserFileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "link",
        "datetime_uploaded",
    )
    list_display_links = (
        "id",
        "link",
    )
