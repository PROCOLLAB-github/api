from django.apps import AppConfig


class ProjectRatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "project_rates"
    verbose_name = "Оценка проектов"

    def ready(self) -> None:
        import project_rates.signals  # noqa F:401
