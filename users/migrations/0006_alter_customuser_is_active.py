# Generated by Django 4.1.2 on 2022-10-20 21:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_remove_customuser_photo_address_customuser_avatar"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="is_active",
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
