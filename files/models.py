import reprlib

from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class UserFile(models.Model):
    """
    UserFile model

    Attributes:
        link: Link to the file on the CDN
        user: User who uploaded the file
        datetime_uploaded: Datetime when the file was uploaded
        name: Name of the file
        extension: Extension of the file
        size: Size of the file in bytes
    """

    link = models.URLField(primary_key=True, null=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    datetime_uploaded = models.DateTimeField(auto_now_add=True)
    name = models.TextField(blank=False, default="file")
    extension = models.TextField(blank=True, default="")
    mime_type = models.CharField(max_length=256, default="")
    size = models.PositiveBigIntegerField(null=False, blank=True, default=1)

    def __str__(self):
        filename_with_extension = f"{self.name}.{self.extension}"
        return f"UserFile<{reprlib.repr(filename_with_extension)}>"

    class Meta:
        verbose_name = "Файл"
        verbose_name_plural = "Файлы"
        ordering = ["-datetime_uploaded"]
