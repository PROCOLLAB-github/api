# Generated by Django 4.1.3 on 2023-07-03 20:59

from django.db import migrations, models


def set_up_ordering_score(apps, schema_editor):
    CustomUser = apps.get_model("users", "CustomUser")

    for user in CustomUser.objects.all():
        user.ordering_score = user.calculate_ordering_score()
        user.save()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0036_userlink"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="ordering_score",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AlterModelOptions(
            name="customuser",
            options={
                "ordering": ["-ordering_score"],
                "verbose_name": "Пользователь",
                "verbose_name_plural": "Пользователи",
            },
        ),
        migrations.RunPython(set_up_ordering_score)
    ]