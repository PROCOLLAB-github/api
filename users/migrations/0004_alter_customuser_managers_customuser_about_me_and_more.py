# Generated by Django 4.1.2 on 2022-10-20 12:12

from django.db import migrations, models
import users.managers


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_remove_userinfo_surname_remove_userinfo_username"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="customuser",
            managers=[
                ("objects", users.managers.CustomUserManager()),
            ],
        ),
        migrations.AddField(
            model_name="customuser",
            name="about_me",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="customuser",
            name="birthday",
            field=models.DateField(null=True),
        ),
        migrations.AddField(
            model_name="customuser",
            name="city",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="key_skills",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="organization",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="patronymic",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="photo_address",
            field=models.ImageField(blank=True, upload_to="photos/%Y/%m/%d/"),
        ),
        migrations.AddField(
            model_name="customuser",
            name="region",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="speciality",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="status",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="tags",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="useful_to_project",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="customuser",
            name="email",
            field=models.EmailField(max_length=254, unique=True),
        ),
        migrations.AlterField(
            model_name="customuser",
            name="is_active",
            field=models.BooleanField(default=False),
        ),
        migrations.DeleteModel(
            name="UserInfo",
        ),
    ]
