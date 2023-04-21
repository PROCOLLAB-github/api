from django.apps import AppConfig
from django.conf import settings


class EventsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "events"
    verbose_name = "Мероприятия"

    def ready(self):
        if settings.AUTOPOSTING_ON:
            import events.signals  # noqa: F401
