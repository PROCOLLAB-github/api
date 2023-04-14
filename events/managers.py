from django.db.models import Manager


class LikesOnEventManager(Manager):
    def get_likes_for_list_view(self):
        return (
            self.get_queryset().select_related("user").only("id", "user__id", "event__id")
        )

    def get_or_create(self, user, event):
        return super().get_or_create(user=user, event=event)

    def toggle_like(self, user, event):
        like, created = self.get_or_create(user=user, event=event)
        if not created:
            like.toggle_like()
        return like
