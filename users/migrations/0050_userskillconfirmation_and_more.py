# Generated by Django 4.2.11 on 2024-09-10 15:22

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_alter_skill_options_alter_skilltoobject_options"),
        ("users", "0049_alter_customuser_key_skills_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSkillConfirmation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("confirmed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="skill_confirmations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "skill_to_object",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="confirmations",
                        to="core.skilltoobject",
                    ),
                ),
            ],
            options={
                "verbose_name": "Подтверждение навыка",
                "verbose_name_plural": "Подтверждения навыков",
            },
        ),
        migrations.AddConstraint(
            model_name="userskillconfirmation",
            constraint=models.UniqueConstraint(
                fields=("skill_to_object", "confirmed_by"),
                name="unique_skill_confirmed_by",
            ),
        ),
    ]
