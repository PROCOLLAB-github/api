# Generated by Django 4.1.7 on 2023-04-14 16:25

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("events", "0010_alter_event_likes_alter_event_short_text_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="event",
            name="likes",
        ),
        migrations.CreateModel(
            name="LikesOnEvent",
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
                ("is_liked", models.BooleanField(default=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="likes",
                        to="events.event",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="likes_on_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Лайк на мероприятие",
                "verbose_name_plural": "Лайки на мероприятия",
                "unique_together": {("user", "event")},
            },
        ),
    ]
