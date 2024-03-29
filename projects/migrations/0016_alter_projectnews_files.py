# Generated by Django 4.2 on 2023-06-14 08:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0003_userfile_extension_userfile_name_userfile_size"),
        ("projects", "0015_projectnews_files"),
    ]

    operations = [
        migrations.AlterField(
            model_name="projectnews",
            name="files",
            field=models.ManyToManyField(
                blank=True, related_name="projects_news", to="files.userfile"
            ),
        ),
    ]
