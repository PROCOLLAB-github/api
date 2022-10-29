# Generated by Django 4.1.2 on 2022-10-29 14:36

from django.db import migrations, models
import users.models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0007_alter_customuser_user_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="user_type",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, "Администратор"),
                    (1, "Участник"),
                    (2, "Ментор"),
                    (3, "Эксперт"),
                    (4, "Инвестор"),
                ],
                default=users.models.get_default_user_type,
            ),
        ),
        migrations.DeleteModel(
            name="UserType",
        ),
    ]
