from django.db import models
from events.constants import VERBOSE_EVENT_TYPE

# from django.contrib.auth.models import User
from django.conf import settings


class Event(models.Model):
    """
    Event model

     Attributes:
        title: A CharField event title.
        text: A TextField event text content.
        short_text: A TextField event short text content.
        cover_url = models.URLField(null=False)
        # datetime_created: A DateTimeField indicating date of creation.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
        tg_message_id: A IntegerField Telegram messaage id (for edit message)
        link: URLField url to company website
        event_type: ChoiceField choice from "online", "offline" and "offline and online"
        prize: CharField described what the person will get
        favorites: ManyToManyField User can select favorite events
        registered: ManyToManyField list of registered users
        views: BigIntegerField
        likes: ManyToManyField likes from users
    """

    title = models.CharField(max_length=256, null=False)
    text = models.TextField(null=False)
    short_text = models.TextField(
        max_length=256, blank=True, help_text="Текст для поста в телеграм"
    )
    cover_url = models.URLField(null=False)
    datetime_of_event = models.DateTimeField(verbose_name="Дата проведения", null=False)

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )
    tg_message_id = models.IntegerField(blank=True, null=True)
    link = models.URLField(null=False)
    event_type = models.PositiveSmallIntegerField(choices=VERBOSE_EVENT_TYPE)
    prize = models.CharField(max_length=128, null=False)
    favorites = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="favorites"
    )
    registered_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="events"
    )
    views = models.BigIntegerField(default=0)
    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="likes"
    )

    def __str__(self):
        return f"Event<{self.id}> - {self.title}"

    class Meta:
        verbose_name = "Мероприятие"
        verbose_name_plural = "Мероприятия"
