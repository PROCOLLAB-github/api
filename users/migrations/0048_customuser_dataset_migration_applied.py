# Generated by Django 4.2.11 on 2024-07-05 13:14

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0047_auto_20240301_1531"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="dataset_migration_applied",
            field=models.BooleanField(
                blank=True,
                default=False,
                help_text="Yes если оба поля `v2_speciality` и `skills` есть, No если поля не перенеслись",
                null=True,
                verbose_name="Временная мера для переноса навыка",
            ),
        ),
    ]
