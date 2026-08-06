from django.db import models
from django_stubs_ext.db.models import TypedModelMeta

from invites.managers import InviteManager
from projects.models import Project
from users.models import CustomUser


class Invite(models.Model):
    """Invite model

    This model is used to store the information about the invitation to the project.

    Attributes:
        project: A ForeignKey referring to the Project model, who sent out the invite
        user: A ForeignKey referring to the user, who got the invite
        motivational_letter: A TextField where the project can tell the user why they need him
        is_accepted: A BooleanField indicating whether the receiver accepted the invite or declined it
        invited_by: Пользователь, который создал приглашение
        is_revoked: Признак исторически сохраненного отзыва
        resolved_at: Дата принятия, отклонения или отзыва
        datetime_created: A DateTimeField indicating date of creation
        datetime_updated: A DateTimeField indicating date of update
    """

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_REVOKED = "revoked"

    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    invited_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_project_invites",
        verbose_name="Кем приглашен",
    )

    motivational_letter = models.TextField(
        max_length=4096, blank=True, null=True, default=None
    )
    role = models.CharField(max_length=128, blank=True, null=True)
    specialization = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default=None,
        verbose_name="Специализация",
    )
    is_accepted = models.BooleanField(blank=False, null=True, default=None)
    is_revoked = models.BooleanField(default=False, verbose_name="Отозвано")
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата обработки",
    )

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата обновления", null=False, auto_now=True
    )

    objects = InviteManager()

    def __str__(self) -> str:
        return f'Invite from project "{self.project.name}" to {self.user.get_full_name()}'

    @property
    def status(self) -> str:
        """Возвращает lifecycle-статус без изменения legacy `is_accepted`."""
        if self.is_revoked:
            return self.STATUS_REVOKED
        if self.is_accepted is True:
            return self.STATUS_ACCEPTED
        if self.is_accepted is False:
            return self.STATUS_DECLINED
        return self.STATUS_PENDING

    @property
    def is_pending(self) -> bool:
        return self.is_accepted is None and not self.is_revoked

    class Meta(TypedModelMeta):
        verbose_name = "Приглашение"
        verbose_name_plural = "Приглашения"
        ordering = ["-datetime_created"]
        constraints = [
            # Завершенные приглашения остаются в истории и не мешают
            # повторному приглашению того же пользователя.
            models.UniqueConstraint(
                fields=["project", "user"],
                condition=models.Q(is_accepted__isnull=True, is_revoked=False),
                name="uniq_pending_project_invite",
            ),
            models.CheckConstraint(
                check=models.Q(is_revoked=False) | models.Q(is_accepted__isnull=True),
                name="invite_revoked_unaccepted",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "is_accepted", "is_revoked", "datetime_created"],
                name="invite_user_state_idx",
            ),
            models.Index(
                fields=[
                    "project",
                    "is_accepted",
                    "is_revoked",
                    "datetime_created",
                ],
                name="invite_project_state_idx",
            ),
        ]
