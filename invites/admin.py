from django.contrib import admin

from invites.models import Invite
from projects.team_admin import TeamValidationAdminMixin


@admin.register(Invite)
class InviteAdmin(TeamValidationAdminMixin, admin.ModelAdmin):
    readonly_fields = ("is_accepted",)

    fields = [
        "project",
        "program_link",
        "user",
        "motivational_letter",
        "role",
        "specialization",
        "is_accepted",
    ]
