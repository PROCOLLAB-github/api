from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from core.models import Like, View
from files.models import UserFile
from news.managers import NewsManager
from django_stubs_ext.db.models import TypedModelMeta


class News(models.Model):
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
