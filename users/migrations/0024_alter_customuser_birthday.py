# Generated by Django 4.1.3 on 2022-12-11 20:54

from django.db import migrations, models
import users.validators


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0023_alter_customuser_options_alter_customuser_birthday_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="birthday",
            field=models.DateField(validators=[users.validators.user_birthday_validator]),
        ),
    ]
