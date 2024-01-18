# Generated by Django 4.2.3 on 2024-01-14 00:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_skillcategory_specializationtoobject_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="skill",
            options={
                "ordering": ["category", "name"],
                "verbose_name": "Навык",
                "verbose_name_plural": "Навыки",
            },
        ),
        migrations.AlterModelOptions(
            name="skillcategory",
            options={
                "ordering": ["name"],
                "verbose_name": "Категория навыка",
                "verbose_name_plural": "Категории навыков",
            },
        ),
        migrations.RenameField(
            model_name="skill",
            old_name="skill",
            new_name="name",
        ),
        migrations.RenameField(
            model_name="skillcategory",
            old_name="category",
            new_name="name",
        ),
    ]