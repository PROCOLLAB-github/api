# Generated by Django 4.2.11 on 2024-09-02 16:01

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import users.validators


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0048_customuser_dataset_migration_applied"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="key_skills",
            field=models.CharField(
                blank=True,
                help_text="Устаревшее поле -> skills",
                max_length=512,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="customuser",
            name="organization",
            field=models.CharField(
                blank=True,
                help_text="Устаревшее поле -> UserEducation",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="customuser",
            name="speciality",
            field=models.CharField(
                blank=True,
                help_text="Устаревшее поле -> v2_speciality",
                max_length=255,
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="UserEducation",
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
                (
                    "organization_name",
                    models.CharField(
                        max_length=255, verbose_name="Наименование организации"
                    ),
                ),
                (
                    "description",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        verbose_name="Краткое описание",
                    ),
                ),
                (
                    "entry_year",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        validators=[users.validators.user_entry_year_education_validator],
                        verbose_name="Год поступления",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="education",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Образование",
                "verbose_name_plural": "Образование",
            },
        ),
    ]
