from django.contrib.auth import get_user_model
from django.db import models
from industries.models import Industry

from projects.helpers import VERBOSE_STEPS, get_default_achievements

User = get_user_model()


class Project(models.Model):
    """
    # TODO verbose names for fields
    Project model

     Attributes:
        name: A CharField name of the project.
        description: A TextField description of the project.
        short_description: A TextField short description of the project.
        achievements: A JSONField which contains title and status of the achievement.
        region: A CharField region of the project.
        step: A PositiveSmallIntegerField which indicates status of the project
            according to VERBOSE_STEPS.
        industry: A ForeignKey referring to the Industry model.
        presentation_address: A TextField presentation URL address.
        image_address: A TextField image URL address.
        collaborators: A ManyToManyField collaborators of the project.
        leader: A ForeignKey referring to the User model.
        draft: A boolean indicating if Project is a draft.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_update: A DateTimeField indicating date of update.
    """

    name = models.CharField(max_length=256, null=False)
    description = models.TextField(blank=True)
    short_description = models.TextField(blank=True)

    # TODO Achievement model
    achievements = models.JSONField(blank=False, default=get_default_achievements)
    region = models.CharField(max_length=256, blank=True)

    step = models.PositiveSmallIntegerField(choices=VERBOSE_STEPS, null=False)

    industry = models.ForeignKey(
        Industry,
        on_delete=models.SET_NULL,
        null=True,
        related_name="projects",
    )
    # TODO think about naming
    presentation_address = models.TextField(blank=True)
    image_address = models.TextField(blank=True)

    collaborators = models.ManyToManyField(User, related_name="projects")

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

    def __str__(self):
        return f"Project<{self.id}>"

    class Meta:
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"
