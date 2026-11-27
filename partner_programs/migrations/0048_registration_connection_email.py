import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("partner_programs", "0047_organizer_guide_seen")]

    operations = [
        migrations.AlterField(
            model_name="registrationconnectionnotification",
            name="delivery_status",
            field=models.CharField(
                choices=[
                    (value, value)
                    for value in ("queued", "sent", "failed", "cancelled", "in_app_only")
                ],
                default="queued",
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="RegistrationConnectionEmail",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("email", models.EmailField(max_length=254)),
                ("emailed_at", models.DateTimeField(blank=True, null=True)),
                ("delivery_status", models.CharField(default="queued", max_length=12)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_deliveries",
                        to="partner_programs.registrationconnectionrequest",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("request", "email"), name="unique_connection_request_email"
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["delivery_status", "id"], name="connection_email_status_idx"
                    ),
                ],
            },
        ),
    ]
