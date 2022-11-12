from django.contrib import admin

from invites.models import Invite


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    fields = [""]
