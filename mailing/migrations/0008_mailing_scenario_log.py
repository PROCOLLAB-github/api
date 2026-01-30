from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0015_partnerprogram_publish_projects_after_finish"),
        ("mailing", "0007_alter_mailingschema_options_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MailingScenarioLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scenario_code", models.CharField(max_length=128)),
                ("scheduled_for", models.DateField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")], default="pending", max_length=16)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True, null=True)),
                ("datetime_created", models.DateTimeField(auto_now_add=True)),
                ("datetime_updated", models.DateTimeField(auto_now=True)),
                (
                    "program",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="mailing_scenario_logs",
                        to="partner_programs.partnerprogram",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="mailing_scenario_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Лог сценария рассылки",
                "verbose_name_plural": "Логи сценариев рассылки",
                "unique_together": {("scenario_code", "program", "user", "scheduled_for")},
            },
        ),
        migrations.AddIndex(
            model_name="mailingscenariolog",
            index=models.Index(fields=["scenario_code", "scheduled_for"], name="mailing_ma_scenari_73b1f9_idx"),
        ),
        migrations.AddIndex(
            model_name="mailingscenariolog",
            index=models.Index(fields=["program", "scheduled_for"], name="mailing_ma_program_b9dcf9_idx"),
        ),
        migrations.AddIndex(
            model_name="mailingscenariolog",
            index=models.Index(fields=["user", "scheduled_for"], name="mailing_ma_user_id_0e2a92_idx"),
        ),
    ]
