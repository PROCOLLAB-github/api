from django.apps import AppConfig


class KanbanConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kanban"

    def ready(self):
        from kanban import signals  # noqa: F401
