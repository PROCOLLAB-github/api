# Generated by Django 4.2.3 on 2023-09-30 09:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mailing", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mailingschema",
            name="schema",
            field=models.JSONField(default=None, null=True),
        ),
    ]
