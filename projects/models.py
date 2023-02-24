from typing import Optional

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import UniqueConstraint
from industries.models import Industry
from projects.helpers import VERBOSE_STEPS
from projects.managers import AchievementManager, ProjectManager
from users.models import CustomUser

User = get_user_model()


class Project(models.Model):
    """
    Project model

     Attributes:
        name: A CharField name of the project.
        description: A TextField description of the project.
        region: A CharField region of the project.
        step: A PositiveSmallIntegerField which indicates status of the project
            according to VERBOSE_STEPS.
        industry: A ForeignKey referring to the Industry model.
        presentation_address: A URLField presentation URL address.
        image_address: A URLField image URL address.
        leader: A ForeignKey referring to the User model.
        draft: A boolean indicating if Project is a draft.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    name = models.CharField(max_length=256, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    region = models.CharField(max_length=256, null=True, blank=True)
    step = models.PositiveSmallIntegerField(choices=VERBOSE_STEPS, null=True, blank=True)

    industry = models.ForeignKey(
        Industry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects",
    )
    presentation_address = models.URLField(null=True, blank=True)
    image_address = models.URLField(null=True, blank=True)

    leader = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="leaders_projects",  # projects in which this user is the leader
    )

    draft = models.BooleanField(blank=False, default=True)

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )

    objects = ProjectManager()

    views_count = models.PositiveIntegerField(default=0)

    def increment_views_count(self):
        self.views_count += 1
        self.save()

    def get_short_description(self) -> Optional[str]:
        return self.description[:90] if self.description else None

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        # if every field is filled, set draft to false
        if (
            self.name
            and self.description
            and self.region
            and (self.step is not None)
            and self.industry
            and self.presentation_address
            and self.image_address
        ):
            self.draft = False
        super().save(force_insert, force_update, using, update_fields)

    def __str__(self):
        return f"Project<{self.id}> - {self.name}"

    class Meta:
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"


class Achievement(models.Model):
    """
    Achievement model

     Attributes:
        title: A CharField title of the achievement.
        status: A CharField place or status of the achievement.
        project: A ForeignKey referring to the Project model.
    """

    title = models.CharField(max_length=256, null=False)
    status = models.CharField(max_length=256, null=False)

    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, related_name="achievements"
    )

    objects = AchievementManager()

    def __str__(self):
        return f"Achievement<{self.id}>"

    class Meta:
        verbose_name = "Достижение"
        verbose_name_plural = "Достижения"


class Collaborator(models.Model):
    """
    Project collaborator model

    Attributes:
        user: A ForeignKey referencing the user who is collaborating in the project.
        project: A ForeignKey referencing the project the user is collaborating in.
        role: A CharField meaning the role the user is fulfilling in the project.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    user = models.ForeignKey(
        CustomUser,
        models.CASCADE,
        verbose_name="Пользователь",
        related_name="collaborations",
    )
    project = models.ForeignKey(Project, models.CASCADE, verbose_name="Проект")
    role = models.CharField("Роль", max_length=1024, blank=True, null=True)

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )

    class Meta:
        verbose_name = "Коллаборатор"
        verbose_name_plural = "Коллабораторы"
        constraints = [
            UniqueConstraint(
                fields=[
                    "project",
                    "user",
                ],
                name="unique_collaborator",
            )
        ]
