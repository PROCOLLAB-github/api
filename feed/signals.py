from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from news.models import News


from vacancy.models import Vacancy


@receiver(post_save, sender=Vacancy)
def create_news_on_save(sender, instance, created, **kwargs):
    if created:
        content_type = ContentType.objects.filter(model="vacancy").first()
        news_instance, created = News.objects.get_or_create(
            content_type=content_type, object_id=instance.id
        )
