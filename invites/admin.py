from django.contrib import admin

from invites.models import Invite


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    fields = ["project", "user", "motivational_letter", "role", "specialization", "is_accepted"]
