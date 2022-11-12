from django.contrib import admin

from files.models import UserFile


@admin.register(UserFile)
class UserFileAdmin(admin.ModelAdmin):
    list_display = (
        "link",
        "user",
        "datetime_uploaded",
    )
    list_display_links = ("link",)
