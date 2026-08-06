from django.db.models import Manager


class InviteManager(Manager):
    def get_invite_for_list_view(self):
        return self.get_queryset().select_related(
            "project",
            "project__leader",
            "user",
            "invited_by",
        )

    def pending(self):
        return self.get_queryset().filter(
            is_accepted__isnull=True,
            is_revoked=False,
        )
