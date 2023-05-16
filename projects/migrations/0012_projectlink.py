# Generated by Django 4.2 on 2023-05-16 21:02

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0011_project_views_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectLink",
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
                ("link", models.URLField()),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="links",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ссылка проекта",
                "verbose_name_plural": "Ссылки проектов",
                "unique_together": {("project", "link")},
            },
        ),
    ]
