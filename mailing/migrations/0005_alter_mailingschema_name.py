# Generated by Django 4.2.3 on 2023-10-01 14:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mailing", "0004_alter_mailingschema_schema"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mailingschema",
            name="name",
            field=models.CharField(max_length=100, unique=True),
        ),
    ]
