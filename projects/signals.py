from django.db.models.signals import post_save
from django.dispatch import receiver

from chats.models import ProjectChat
from feed.services import delete_news_for_model, create_news_for_model
from projects.models import Collaborator, Project
from vacancy.models import Vacancy


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


@receiver(post_save, sender=Project)
def update_vacancy(sender, instance, created, **kwargs):
    vacancies = Vacancy.objects.filter(project=instance)
    old_values = vacancies.values_list("is_active", flat=True)
    vacancies.update(is_active=False if instance.draft else True)
    new_values = vacancies.values_list("is_active", flat=True)

    vacancies_list = list(vacancies)

    for i in range(len(new_values)):
        old = old_values[i]
        new = new_values[i]
        if old != new and new is False:
            delete_news_for_model(vacancies_list[i])
        elif old != new and new is True:
            create_news_for_model(vacancies_list[i])
