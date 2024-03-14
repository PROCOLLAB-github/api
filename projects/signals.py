from django.db.models.signals import post_save
from django.dispatch import receiver

from chats.models import ProjectChat
from projects.models import Collaborator, Project
from django.core.cache import cache


@receiver(post_save, sender=Project)
def create_project(sender, instance, created, **kwargs):
    """
    Creates collaborator for the project leader and ProjectChat on project creation
    """

    if not instance.draft:
        ProjectChat.objects.get_or_create(project=instance)

    if created:
        Collaborator.objects.create(
            user=instance.leader, project=instance, role="Основатель"
        )

    # invalidating cache from ProjectList view
    keys = cache.keys("*project_list*")
    cache.delete_many(keys)
