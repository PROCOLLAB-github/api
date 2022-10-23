from django.db import models


class News(models.Model):
    """
    News model

     Attributes:
        title: A CharField news title.
        text: A TextField news text content.
        short_text: A TextField news short text content.
        cover_url: A URLField link to news cover image.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    title = models.CharField(max_length=256, null=False)

    text = models.TextField(null=False)

    short_text = models.TextField(max_length=256, blank=True)

    cover_url = models.URLField(null=False)

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )

    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )

    def __str__(self):
        return f"News<{self.id}> - {self.title}"

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
