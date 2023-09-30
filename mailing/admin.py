from django.contrib import admin
from .models import MailingSchema


@admin.register(MailingSchema)
class MailingSchemaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
    )
