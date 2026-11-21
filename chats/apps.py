from django.apps import AppConfig


class ChatsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "chats"
    verbose_name = "Чаты"

    def ready(self):
        from chats import signals  # noqa: F401
