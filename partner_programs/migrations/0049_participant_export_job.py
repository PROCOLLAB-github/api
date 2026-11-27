import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0048_registration_connection_email"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ParticipantExportJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source", models.CharField(max_length=8)),
                ("parameters", models.JSONField(default=dict)),
                ("status", models.CharField(default="queued", max_length=8)),
                ("detail", models.CharField(blank=True, max_length=255)),
                ("filename", models.TextField(blank=True)),
                ("content", models.BinaryField(editable=False, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("started_at", models.DateTimeField(null=True)),
                ("completed_at", models.DateTimeField(null=True)),
                (
                    "program",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="partner_programs.partnerprogram",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["program", "requested_by", "source", "-created_at"],
                        name="participant_export_owner",
                    ),
                    models.Index(
                        fields=["status", "created_at"], name="participant_export_queue"
                    ),
                ],
            },
        )
    ]
