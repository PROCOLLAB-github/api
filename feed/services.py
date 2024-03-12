from django.contrib.contenttypes.models import ContentType

from feed.constants import SIGNALS_MODELS
from news.models import News


def delete_news_for_model(instance: SIGNALS_MODELS):
    content_type = ContentType.objects.get_for_model(instance)
    obj = News.objects.filter(
        text="", content_type=content_type, object_id=instance.id
    ).first()
    if obj:
        obj.delete()


def create_news_for_model(instance: SIGNALS_MODELS):
    content_type = ContentType.objects.get_for_model(instance)
    News.objects.get_or_create(text="", content_type=content_type, object_id=instance.id)
