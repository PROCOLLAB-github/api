from django.contrib import admin

from invites.models import Invite


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    fields = [
        "project",
        "user",
        "invited_by",
        "motivational_letter",
        "role",
        "specialization",
        "is_accepted",
        "is_revoked",
        "resolved_at",
    ]
