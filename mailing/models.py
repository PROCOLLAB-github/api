import os
import uuid

from django.db import models
from .constants import get_default_mailing_schema

from django_stubs_ext.db.models import TypedModelMeta


def get_template_path(instance, filename):
    ext = filename.split(".")[-1]
    filename = "%s.%s" % (uuid.uuid4(), ext)
    return os.path.join("templates/mailing/emails", filename)


class MailingSchema(models.Model):
    name = models.CharField(max_length=100, unique=True)
    schema = models.JSONField(default=get_default_mailing_schema, null=True, blank=True)
    template = models.TextField()

    class Meta(TypedModelMeta):
        verbose_name = "Схема шаблона письма"
        verbose_name_plural = "Схемы шаблонов писем"

    def __str__(self):
        return f"MailingSchema<{self.name}>"
