# Generated by Django 4.1.2 on 2022-10-16 23:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_remove_customuser_username'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userinfo',
            name='surname',
        ),
        migrations.RemoveField(
            model_name='userinfo',
            name='username',
        ),
    ]
