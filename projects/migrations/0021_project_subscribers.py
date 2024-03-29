# Generated by Django 4.2.3 on 2023-11-14 20:07

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("projects", "0020_project_cover_defaultprojectcover"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="subscribers",
            field=models.ManyToManyField(
                related_name="subscribed_projects",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Подписчики",
            ),
        ),
    ]
