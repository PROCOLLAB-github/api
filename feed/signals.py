from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from news.models import News
from projects.models import Project

from vacancy.models import Vacancy


@receiver(post_save, sender=Vacancy)
def create_news_on_save(sender, instance, created, **kwargs):
    if created:
        content_type = ContentType.objects.get_for_model(Vacancy)
        news_instance, created = News.objects.get_or_create(
            content_type=content_type, object_id=instance.id
        )


@receiver(post_save, sender=Project)
def create_news_on_created_project(sender, instance, created, **kwargs):
    if not instance.draft:
        content_type = ContentType.objects.get_for_model(Project)
        news_instance, created = News.objects.get_or_create(
            content_type=content_type, object_id=instance.id
        )
