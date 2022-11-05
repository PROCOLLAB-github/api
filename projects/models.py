from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import UniqueConstraint

from industries.models import Industry
from projects.helpers import VERBOSE_STEPS
from projects.managers import ProjectManager, AchievementManager
from users.models import CustomUser

User = get_user_model()


class Project(models.Model):
    """
    Project model

     Attributes:
        name: A CharField name of the project.
        description: A TextField description of the project.
        short_description: A TextField short description of the project.
        region: A CharField region of the project.
        step: A PositiveSmallIntegerField which indicates status of the project
            according to VERBOSE_STEPS.
        industry: A ForeignKey referring to the Industry model.
        presentation_address: A URLField presentation URL address.
        image_address: A URLField image URL address.
        collaborators: A ManyToManyField collaborators of the project.
        leader: A ForeignKey referring to the User model.
        draft: A boolean indicating if Project is a draft.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    name = models.CharField(max_length=256, null=False)
    description = models.TextField(blank=True)
    short_description = models.TextField(blank=True)
    region = models.CharField(max_length=256, blank=True)
    step = models.PositiveSmallIntegerField(choices=VERBOSE_STEPS, null=False)

    industry = models.ForeignKey(
        Industry,
        on_delete=models.SET_NULL,
        null=True,
        related_name="projects",
    )
    # TODO think about naming
    presentation_address = models.URLField(blank=True)
    image_address = models.URLField(blank=True)

    collaborators = models.ManyToManyField(
        to=User,
        related_name="projects",
        through="projects.Collaborator",
        through_fields=("project", "user"),
    )

    leader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
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
        Project,
        on_delete=models.SET_NULL,
        null=True,
        related_name="achievements",
    )

    objects = AchievementManager()

    def __str__(self):
        return f"Achievement<{self.id}>"

    class Meta:
        verbose_name = "Достижение"
        verbose_name_plural = "Достижения"


class Collaborator(models.Model):
    """Project collaborator model"""

    user = models.ForeignKey(CustomUser, models.CASCADE, verbose_name="Пользователь")
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
            UniqueConstraint(fields=['project', 'user', ], name='unique_collaorator')
        ]
