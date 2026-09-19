# Сгенерировано Django 4.2.11: nullable-изображение без изменения исторических данных.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_add_program_notification_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='image_url',
            field=models.URLField(blank=True, null=True),
        ),
    ]
