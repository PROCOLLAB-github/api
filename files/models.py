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
    link = models.URLField(primary_key=True, null=False)
    datetime_uploaded = models.DateTimeField(auto_now_add=True)

    def delete(self, using=None, keep_parents=False):
        # TODO: add request to CDN to delete the object
        super(UserFile, self).delete(using=using, keep_parents=keep_parents)

    def __str__(self):
        return f"UserFile by {self.user}, {self.link}"
