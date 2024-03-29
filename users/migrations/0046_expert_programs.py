# Generated by Django 4.2.3 on 2024-02-26 15:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("partner_programs", "0004_auto_20231230_0002"),
        ("users", "0045_alter_customuser_v2_speciality"),
    ]

    operations = [
        migrations.AddField(
            model_name="expert",
            name="programs",
            field=models.ManyToManyField(
                blank=True, related_name="experts", to="partner_programs.partnerprogram"
            ),
        ),
    ]
