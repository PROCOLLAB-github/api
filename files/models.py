from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class UserFile(models.Model):
    """
    UserFile model

    Attributes:
        user: User who uploaded the file
        link: Link to the file on the CDN
        datetime_uploaded: Datetime when the file was uploaded
    """

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    link = models.URLField(null=False)
    datetime_uploaded = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"UserFile<{self.id}> - {self.link}"
