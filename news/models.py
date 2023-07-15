from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from news.managers import NewsManager


class NewsTag(models.Model):
    """News tag model

    Attributes:
        name: A CharField for the tag's name
        description: A CharField for the tag's description
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    name = models.CharField("Название тега", max_length=256, blank=False, null=False)
    # hopefully 512 characters are enough for any tag description
    description = models.CharField("Описание тега", max_length=512, blank=True, null=True)

    # probably not really needed here but won't hurt
    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )

    def __str__(self):
        return f"NewsTag<{self.id}> - {self.name}"

    class Meta:
        verbose_name = "Тег"
        verbose_name_plural = "Теги"


class News(models.Model):
    """
    News model

     Attributes:
        title: A CharField news title.
        text: A TextField news text content.
        short_text: A TextField news short text content.
        cover_url: A URLField link to news cover image.
        tags: A ManyToManyField listing all tags of this news object
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    title = models.CharField(max_length=256, null=False)
    text = models.TextField(null=False)
    short_text = models.TextField(max_length=256, blank=True)
    cover_url = models.URLField(null=False)

    tags = models.ManyToManyField(NewsTag, blank=True, verbose_name="Список тегов")

    # generic relation to project/program/ something else possibly
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="news", null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )

    objects = NewsManager()

    @property
    def tags_str(self):
        """Formats tags to string

        Returns: List of tags' names separated by a comma
        """
        return ", ".join([i.name for i in self.tags.all()])

    def __str__(self):
        return f"News<{self.id}> - {self.title}"

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
