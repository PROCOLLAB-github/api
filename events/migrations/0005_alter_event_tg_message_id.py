# Generated by Django 4.1.7 on 2023-03-13 08:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0004_alter_event_tg_message_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='tg_message_id',
            field=models.IntegerField(blank=True, editable=False, null=True),
        ),
    ]