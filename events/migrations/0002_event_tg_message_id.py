# Generated by Django 4.1.3 on 2023-03-06 14:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='tg_message_id',
            field=models.IntegerField(default=-1),
        ),
    ]
