# Generated by Django 4.1.3 on 2023-04-03 12:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0008_merge_0005_alter_event_tg_message_id_0007_event_tags"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="datetime_created",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="event",
            name="datetime_of_event",
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name="event",
            name="datetime_updated",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="event",
            name="tg_message_id",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
