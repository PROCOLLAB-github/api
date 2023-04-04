# Generated by Django 4.1.3 on 2023-04-04 11:48

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chats", "0010_alter_filetomessage_file"),
    ]

    operations = [
        migrations.AlterField(
            model_name="filetomessage",
            name="direct_message",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="file_to_message",
                to="chats.directchatmessage",
            ),
        ),
        migrations.AlterField(
            model_name="filetomessage",
            name="project_message",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="file_to_message",
                to="chats.projectchatmessage",
            ),
        ),
    ]