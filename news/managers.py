from django.contrib.contenttypes.models import ContentType
from django.db import models


class NewsManager(models.Manager):
    def get_news(self, obj):
        obj_type = ContentType.objects.get_for_model(obj)
        return self.get_queryset().filter(content_type=obj_type, object_id=obj.id)

    def add_news(self, obj, **kwargs):
        obj_type = ContentType.objects.get_for_model(obj)
        news = self.create(content_type=obj_type, object_id=obj.id, **kwargs)
        return news
