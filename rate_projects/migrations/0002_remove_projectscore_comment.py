# Generated by Django 4.2.3 on 2024-02-19 17:04

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rate_projects", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="projectscore",
            name="comment",
        ),
    ]