# Generated by Django 4.1.2 on 2022-10-27 15:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_alter_customuser_avatar"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserType",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (0, "Администратор"),
                            (1, "Участник"),
                            (2, "Ментор"),
                            (3, "Эксперт"),
                            (4, "Инвестор"),
                        ],
                        primary_key=True,
                        serialize=False,
                    ),
                ),
            ],
        ),
    ]
