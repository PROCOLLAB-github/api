from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def set_existing_news_audiences(apps, schema_editor):
    News = apps.get_model("news", "News")
    ContentType = apps.get_model("contenttypes", "ContentType")

    News.objects.all().update(audience="platform")
    program_content_type_id = (
        ContentType.objects.filter(
            app_label="partner_programs",
            model="partnerprogram",
        )
        .values_list("id", flat=True)
        .first()
    )
    if program_content_type_id is not None:
        # Старые новости программ считаются внутренними: миграция не должна
        # случайно опубликовать их во всей платформе.
        News.objects.filter(content_type_id=program_content_type_id).update(
            audience="program_participants"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("news", "0009_news_pin"),
    ]

    operations = [
        migrations.AddField(
            model_name="news",
            name="audience",
            field=models.CharField(
                choices=[
                    ("platform", "Вся платформа"),
                    ("program_participants", "Участники программы"),
                ],
                db_index=True,
                default="platform",
                max_length=24,
                verbose_name="Аудитория",
            ),
        ),
        migrations.RunPython(
            set_existing_news_audiences,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="news",
            constraint=models.CheckConstraint(
                check=models.Q(audience__in=("platform", "program_participants")),
                name="news_valid_audience",
            ),
        ),
        migrations.CreateModel(
            name="NewsComment",
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
                ("text", models.TextField(max_length=2000, verbose_name="Текст")),
                (
                    "datetime_created",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="Дата создания",
                    ),
                ),
                (
                    "datetime_updated",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Дата изменения",
                    ),
                ),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="news_comments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Автор",
                    ),
                ),
                (
                    "news",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="news.news",
                        verbose_name="Новость",
                    ),
                ),
            ],
            options={
                "verbose_name": "Комментарий к новости",
                "verbose_name_plural": "Комментарии к новостям",
                "ordering": ["datetime_created", "id"],
                "indexes": [
                    models.Index(
                        fields=["news", "datetime_created"],
                        name="news_comment_order_idx",
                    )
                ],
            },
        ),
    ]
