# Generated by Django 4.1.3 on 2023-03-22 21:01

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chats", "0007_remove_directchatmessage_file_url_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="directchatmessage",
            name="file_url",
        ),
        migrations.RemoveField(
            model_name="projectchatmessage",
            name="file_url",
        ),
    ]
