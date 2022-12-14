# Generated by Django 4.1.2 on 2022-10-29 13:45

from django.db import migrations, models
import django.db.models.deletion
import users.models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_alter_member_useful_to_project_mentor_investor_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="user_type",
            field=models.ForeignKey(
                default=users.models.get_default_user_type,
                on_delete=django.db.models.deletion.SET_DEFAULT,
                related_name="users",
                to="users.usertype",
            ),
        ),
    ]
