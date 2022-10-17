from django.contrib import admin

from industries.models import Industry


@admin.register(Industry)
class IndustryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
    )
    list_display_links = (
        "id",
        "name",
    )
