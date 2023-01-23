from django.db.models.signals import post_save
from django.dispatch import receiver

from chats.models import ProjectChat
from projects.models import Collaborator, Project


@receiver(post_save, sender=Project)
def create_project(sender, instance, created, **kwargs):
    """
    Creates collaborator for the project leader and ProjectChat on project creation
    """

    if created:
        Collaborator.objects.create(
            user=instance.leader, project=instance, role="Основатель"
        )

        ProjectChat.objects.create(project=instance)
