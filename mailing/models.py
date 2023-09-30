import os
import uuid

from django.core.validators import FileExtensionValidator
from django.db import models


def get_template_path(instance, filename):
    ext = filename.split(".")[-1]
    filename = "%s.%s" % (uuid.uuid4(), ext)
    return os.path.join("templates/email", filename)


class MailingSchema(models.Model):
    name = models.CharField(max_length=100, unique=True)
    schema = models.JSONField(default=dict, null=True, blank=True)
    template = models.FileField(
        upload_to=get_template_path,
        validators=[FileExtensionValidator(allowed_extensions=["html"])],
    )

    def __str__(self):
        return self.name
