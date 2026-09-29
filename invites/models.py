from django.db import models, transaction
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
        datetime_created: A DateTimeField indicating date of creation
        datetime_updated: A DateTimeField indicating date of update
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    program_link = models.ForeignKey(
        "partner_programs.PartnerProgramProject",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="team_invites",
    )
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)

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

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата обновления", null=False, auto_now=True
    )

    objects = InviteManager()

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        from projects import team_policy
        from projects.team_errors import TeamError

        if not self.project_id or not self.user_id:
            return
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        try:
            if (
                previous
                and previous.program_link_id
                and previous.program_link_id != self.program_link_id
            ):
                raise TeamError(
                    "invalid_program_context",
                    "Контекст существующего приглашения нельзя изменить.",
                )
            if previous and (
                previous.project_id != self.project_id or previous.user_id != self.user_id
            ):
                raise TeamError(
                    "invalid_invite_fields",
                    "Получателя и проект приглашения нельзя изменить.",
                )
            if previous and previous.is_accepted is not None:
                if any(
                    getattr(previous, field) != getattr(self, field)
                    for field in (
                        "role",
                        "specialization",
                        "motivational_letter",
                        "is_accepted",
                        "program_link_id",
                    )
                ):
                    raise TeamError(
                        "invite_already_processed", "Приглашение уже обработано."
                    )
            if self.is_accepted is None:
                if (
                    type(self)
                    .objects.filter(
                        project_id=self.project_id,
                        user_id=self.user_id,
                        is_accepted__isnull=True,
                    )
                    .exclude(pk=self.pk)
                    .exists()
                ):
                    raise TeamError(
                        "duplicate_pending_invite",
                        "У пользователя уже есть активное приглашение.",
                    )
                link = team_policy.validate_new_member(
                    self.project, self.user_id, program_link_id=self.program_link_id
                )
                if link:
                    self.program_link = link
        except TeamError as error:
            raise ValidationError(
                str(error.detail["detail"]), code=str(error.detail["code"])
            ) from error

    @transaction.atomic
    def save(self, *args, **kwargs):
        from projects.team_policy import lock_team

        self.project = lock_team(self.project_id).project
        # В legacy поле nullable, но blank=False; None — валидный pending lifecycle.
        self.full_clean(
            exclude=["is_accepted"], validate_unique=False, validate_constraints=False
        )
        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        from projects.team_policy import lock_team

        lock_team(self.project_id)
        previous = type(self).objects.select_for_update().filter(pk=self.pk).first()
        if previous and previous.is_accepted is not None:
            raise ValidationError(
                "Приглашение уже обработано.", code="invite_already_processed"
            )
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f'Invite from project "{self.project.name}" to {self.user.get_full_name()}'

    class Meta(TypedModelMeta):
        verbose_name = "Приглашение"
        verbose_name_plural = "Приглашения"
        ordering = ["-datetime_created"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "user"],
                condition=models.Q(is_accepted__isnull=True),
                name="uniq_legacy_pending_invite",
            )
        ]
