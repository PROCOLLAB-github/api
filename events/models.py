from django.contrib.auth import get_user_model
from django.db import models
from taggit.managers import TaggableManager

from events.constants import MAIN_URL, VERBOSE_EVENT_TYPE

User = get_user_model()


class Event(models.Model):
    """
    Event model

     Attributes:
        title: A CharField event title.
        text: A TextField event text content.
        short_text: A TextField event short text content.
        cover_url: A URLField link to event cover image.
        tg_message_id: A IntegerField Telegram message id (for editing message)
        website_url: URLField url to company website
        event_type: PositiveSmallIntegerField choice from "online", "offline" and "offline and online"
        prize: CharField described what the person will get
        favorites: ManyToManyField User can select favorite events
        registered_users: ManyToManyField list of registered users
        views: BigIntegerField
        likes: ManyToManyField likes from users
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
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
    website_url = models.URLField(null=False, default=MAIN_URL)
    event_type = models.PositiveSmallIntegerField(choices=VERBOSE_EVENT_TYPE, default=0)
    prize = models.CharField(max_length=256, null=True)
    favorites = models.ManyToManyField(User, blank=True, related_name="favorites")
    registered_users = models.ManyToManyField(User, blank=True, related_name="events")
    views = models.BigIntegerField(default=0)
    likes = models.ManyToManyField(User, blank=True, related_name="likes")

    tags = TaggableManager()

    def __str__(self):
        return f"Event<{self.id}> - {self.title}"

    class Meta:
        verbose_name = "Мероприятие"
        verbose_name_plural = "Мероприятия"
