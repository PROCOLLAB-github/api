# Generated by Django 4.2.3 on 2023-09-30 09:44

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0005_alter_userfile_options"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="userfile",
            options={
                "ordering": ["datetime_uploaded"],
                "verbose_name": "Файл",
                "verbose_name_plural": "Файлы",
            },
        ),
    ]
