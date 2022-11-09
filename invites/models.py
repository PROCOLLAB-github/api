from django.db import models

from projects.models import Project
from users.models import CustomUser


class Invite(models.Model):
    """Invite model

    Attributes:
        project: A ForeignKey referring to the Project model, who sent out the invite
        user: A ForeignKey referring to the user, who got the invite
        motivational_letter: A TextField where the project can tell the user why they need him
        is_accepted: A BooleanField indicating whether the receiver accepted the invite or declined it
        datetime_created: A DateTimeField indicating date of creation
        datetime_updated: A DateTimeField indicating date of update
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)

    motivational_letter = models.TextField(
        max_length=4096, blank=True, null=True, default=None
    )
    role = models.CharField(
        max_length=128, blank=True, null=True
    )
    is_accepted = models.BooleanField(blank=False, null=True, default=None)

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата обновления", null=False, auto_now=True
    )

    def __str__(self):
        return f'Invite from "{self.project.name}" to {self.user.get_full_name()}'

    class Meta:
        verbose_name = "Приглашение"
        verbose_name_plural = "Приглашения"
        ordering = ["-datetime_created"]
