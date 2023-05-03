# Generated by Django 4.1.3 on 2023-05-03 16:14

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0033_customuser_verification_date_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="onboarding_stage",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                editable=False,
                help_text="0 - не пройден, 1, 2 и 3 - номера стадий онбординга, null(пустое) - онбординг пройден",
                null=True,
                verbose_name="Стадия онбординга",
            ),
        ),
    ]
