# Generated by Django 4.1.2 on 2022-11-17 21:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0006_alter_project_name_alter_project_step"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="collaborator",
            name="unique_collaorator",
        ),
        migrations.AddConstraint(
            model_name="collaborator",
            constraint=models.UniqueConstraint(
                fields=("project", "user"), name="unique_collaborator"
            ),
        ),
    ]
