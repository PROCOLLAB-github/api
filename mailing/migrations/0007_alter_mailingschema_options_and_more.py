# Generated by Django 4.2.3 on 2023-10-27 06:48

from django.db import migrations, models
import mailing.constants


class Migration(migrations.Migration):

    dependencies = [
        ("mailing", "0006_alter_mailingschema_schema_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="mailingschema",
            options={
                "verbose_name": "Схема шаблона письма",
                "verbose_name_plural": "Схемы шаблонов писем",
            },
        ),
        migrations.AlterField(
            model_name="mailingschema",
            name="schema",
            field=models.JSONField(
                blank=True,
                default=mailing.constants.get_default_mailing_schema,
                null=True,
            ),
        ),
    ]
