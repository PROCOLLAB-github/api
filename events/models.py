from django.db import models

# from django.conf import settings


class Event(models.Model):
    """
    Event model

     Attributes:
        title: A CharField event title.
        text: A TextField event text content.
        short_text: A TextField event short text content.
        cover_url: A URLField link to event cover image.
        # datetime_created: A DateTimeField indicating date of creation.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    title = models.CharField(max_length=256, null=False)
    text = models.TextField(null=False)
    short_text = models.TextField(max_length=256, blank=True)
    cover_url = models.URLField(null=False)
    datetime_of_event = models.DateTimeField(verbose_name="Дата проведения", null=False)

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )
    tg_message_id = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"Event<{self.id}> - {self.title}"

    class Meta:
        verbose_name = "Мероприятие"
        verbose_name_plural = "Мероприятия"
