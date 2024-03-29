# Generated by Django 4.1.3 on 2023-03-28 14:05

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0003_userfile_extension_userfile_name_userfile_size"),
        ("chats", "0008_remove_directchatmessage_file_url_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="FileToMessage",
            fields=[
                (
                    "file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="file_to_message",
                        serialize=False,
                        to="files.userfile",
                    ),
                ),
                (
                    "direct_message",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="file_to_direct_message",
                        to="chats.directchatmessage",
                    ),
                ),
                (
                    "project_message",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="file_to_direct_message",
                        to="chats.projectchatmessage",
                    ),
                ),
            ],
            options={
                "verbose_name": "Связка файла и сообщения",
                "verbose_name_plural": "Связки файлов и сообщений",
            },
        ),
    ]
