from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.db import models

User = get_user_model()


class Like(Model):
    """
    Generic Like model based on contenttype
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="likes",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="likes",
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        unique_together = ("user", "content_type", "object_id")
        verbose_name = "Лайк"
        verbose_name_plural = "Лайки"

    def __str__(self):
        return f"Like<{self.user} - {self.content_object}>"
