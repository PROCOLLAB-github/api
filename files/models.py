from django.contrib.auth import get_user_model
from django.db import models

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
    link = models.URLField(primary_key=True, null=False)
    datetime_uploaded = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=512, null=False, blank=False, default="file")
    extension = models.CharField(max_length=32, null=False, blank=True, default="")
    size = models.PositiveBigIntegerField(null=False, blank=False, default=1)

    def __str__(self):
        return f"UserFile by {self.user}, {self.link}"
