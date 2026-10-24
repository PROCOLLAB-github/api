from django.apps import AppConfig


class PartnerProgramsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "partner_programs"
    verbose_name = "Партнерские программы"

    def ready(self):
        from partner_programs import solution_file_signals  # noqa: F401
