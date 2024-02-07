# Generated by Django 4.2.3 on 2024-02-07 11:02

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("projects", "0021_project_subscribers"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("partner_programs", "0004_auto_20231230_0002"),
    ]

    operations = [
        migrations.CreateModel(
            name="Criteria",
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
                ("name", models.CharField(max_length=50, verbose_name="Название")),
                (
                    "description",
                    models.TextField(blank=True, null=True, verbose_name="Описание"),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("str", "Текст"),
                            ("int", "Целочисленное число"),
                            ("float", "Число с плавающей точкой"),
                            ("bool", "Да или нет"),
                        ],
                        max_length=8,
                        verbose_name="Тип",
                    ),
                ),
                (
                    "min_value",
                    models.FloatField(
                        blank=True,
                        help_text="(если есть)",
                        null=True,
                        verbose_name="Минимально допустимое числовое значение",
                    ),
                ),
                (
                    "max_value",
                    models.FloatField(
                        blank=True,
                        help_text="(если есть)",
                        null=True,
                        verbose_name="Максимально допустимое числовое значение",
                    ),
                ),
                (
                    "partner_program",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="criterias",
                        to="partner_programs.partnerprogram",
                    ),
                ),
            ],
            options={
                "verbose_name": "Критерий оценки проекта",
                "verbose_name_plural": "Критерии оценки проектов",
            },
        ),
        migrations.CreateModel(
            name="ProjectScore",
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
                    "value_int",
                    models.IntegerField(
                        blank=True, null=True, verbose_name="Целочисленное значение"
                    ),
                ),
                (
                    "value_float",
                    models.FloatField(
                        blank=True,
                        max_length=50,
                        null=True,
                        verbose_name="Значение с плавающей запятой",
                    ),
                ),
                (
                    "value_bool",
                    models.BooleanField(
                        blank=True, null=True, verbose_name="'Да или нет' значение"
                    ),
                ),
                (
                    "value_str",
                    models.FloatField(
                        blank=True,
                        max_length=50,
                        null=True,
                        verbose_name="Текстовое значение",
                    ),
                ),
                (
                    "criteria",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scores",
                        to="rate_projects.criteria",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scores",
                        to="projects.project",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scores",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Оценка проекта",
                "verbose_name_plural": "Оценки проектов",
                "unique_together": {("criteria", "user", "project")},
            },
        ),
    ]