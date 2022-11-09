from django.db.models import Manager


class InviteManager(Manager):
    def get_invite_for_list_view(self):
        return (
            self.get_queryset()
            .select_related("project", "user")
        )

