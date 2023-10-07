# Generated by Django 4.2.3 on 2023-09-30 09:44

import django.core.validators
from django.db import migrations, models
import mailing.models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MailingSchema",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("schema", models.JSONField()),
                (
                    "template",
                    models.FileField(
                        upload_to=mailing.models.get_template_path,
                        validators=[
                            django.core.validators.FileExtensionValidator(
                                allowed_extensions=["html"]
                            )
                        ],
                    ),
                ),
            ],
        ),
    ]
