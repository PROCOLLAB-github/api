# Generated by Django 4.1.2 on 2022-10-24 21:11

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("industries", "0001_initial"),
        ("projects", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="collaborators",
            field=models.ManyToManyField(
                related_name="projects", to=settings.AUTH_USER_MODEL
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="industry",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="projects",
                to="industries.industry",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="leader",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="leaders_projects",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="achievement",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="achievements",
                to="projects.project",
            ),
        ),
    ]
