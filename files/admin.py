from django.contrib import admin

from files.models import UserFile


@admin.register(UserFile)
class UserFileAdmin(admin.ModelAdmin):
    list_display = (
        "short_link",
        "filename",
        "user",
        "datetime_uploaded",
    )
    list_display_links = (
        "short_link",
        "filename",
        "user",
    )
    search_fields = (
        "link",
        "user__first_name",
        "user__last_name",
    )
    list_filter = (
        "user",
        "datetime_uploaded",
    )

    date_hierarchy = "datetime_uploaded"

    @admin.display(empty_value="Empty filename")
    def filename(self, obj):
        return obj.name

    @admin.display(empty_value="Empty link")
    def short_link(self, obj):
        return obj.link[15:40] + "..." + obj.link[-20:]
