# Generated by Django 4.2.11 on 2024-12-02 11:40

from django.db import migrations, models
import projects.models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0022_alter_project_options_project_is_company"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="cover_image_address",
            field=models.URLField(
                blank=True,
                default=projects.models.DefaultProjectCover.get_random_file_link,
                help_text="If left blank, will set a link to the image from the 'Обложки проектов'",
                null=True,
            ),
        ),
    ]
