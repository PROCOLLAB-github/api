# Generated by Django 4.1.3 on 2023-03-06 14:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0003_alter_event_tg_message_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='tg_message_id',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
