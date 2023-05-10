# Generated by Django 4.1.3 on 2023-04-14 11:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0031_alter_customuser_onboarding_stage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="onboarding_stage",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=None,
                editable=False,
                help_text="null(пустое) - онбординг пройден, 1, 2 и 3 - номера стадий онбординга",
                null=True,
                verbose_name="Стадия онбординга",
            ),
        ),
    ]
