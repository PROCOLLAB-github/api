# Generated by Django 4.1.2 on 2022-10-23 14:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vacancy", "0002_vacancyrequest_is_approve"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vacancyrequest",
            name="is_approve",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
