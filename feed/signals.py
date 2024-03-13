from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from feed.services import create_news_for_model, delete_news_for_model
from projects.models import Project

from vacancy.models import Vacancy


@receiver(post_save, sender=Vacancy)
def create_news_on_save(sender, instance, created, **kwargs):

    if instance.is_active:
        create_news_for_model(instance)
    else:
        delete_news_for_model(instance)


@receiver(post_delete, sender=Vacancy)
def delete_news_vacancy(sender, instance, **kwargs):
    delete_news_for_model(instance)


@receiver(post_save, sender=Project)
def create_news_on_created_project(sender, instance, created, **kwargs):
    if not instance.draft:
        create_news_for_model(instance)
    else:
        delete_news_for_model(instance)


@receiver(post_delete, sender=Project)
def delete_news_project(sender, instance, **kwargs):
    delete_news_for_model(instance)
