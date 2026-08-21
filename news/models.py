from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import Like, View
from files.models import UserFile
from news.managers import NewsManager
from django_stubs_ext.db.models import TypedModelMeta


class News(models.Model):
    class Audience(models.TextChoices):
        PLATFORM = "platform", "Вся платформа"
        PROGRAM_PARTICIPANTS = "program_participants", "Участники программы"

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="news",
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    text = models.TextField(
        null=False,
        blank=False,
    )
    files = models.ManyToManyField(UserFile, related_name="news", blank=True)

    views = GenericRelation(
        View,
        related_query_name="project_views",
    )
    likes = GenericRelation(
        Like,
        related_query_name="project_news",
    )
    pin = models.BooleanField(
        blank=True,
        default=False,
        verbose_name="Закрепить новость",
        help_text="Закрепить новость (пока только для профиля программ)",
    )
    audience = models.CharField(
        max_length=24,
        choices=Audience.choices,
        default=Audience.PLATFORM,
        db_index=True,
        verbose_name="Аудитория",
    )
    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, default=timezone.now
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения",
        null=False,
        auto_now=True,
    )

    objects = NewsManager()

    class Meta(TypedModelMeta):
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
        ordering = ["-datetime_created"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(audience__in=("platform", "program_participants")),
                name="news_valid_audience",
            )
        ]


class NewsComment(models.Model):
    news = models.ForeignKey(
        News,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="Новость",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="news_comments",
        verbose_name="Автор",
    )
    text = models.TextField(max_length=2000, verbose_name="Текст")
    datetime_created = models.DateTimeField(
        default=timezone.now,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата изменения",
    )

    class Meta(TypedModelMeta):
        verbose_name = "Комментарий к новости"
        verbose_name_plural = "Комментарии к новостям"
        ordering = ["datetime_created", "id"]
        indexes = [
            models.Index(
                fields=["news", "datetime_created"],
                name="news_comment_order_idx",
            )
        ]
