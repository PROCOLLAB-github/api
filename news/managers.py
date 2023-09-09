from django.contrib.contenttypes.models import ContentType
from django.db import models


class NewsManager(models.Manager):
    def get_news(self, obj):
        obj_type = ContentType.objects.get_for_model(obj)
        return self.get_queryset().filter(content_type=obj_type, object_id=obj.pk)

    def add_news(self, obj, **kwargs):
        obj_type = ContentType.objects.get_for_model(obj)
        kwargs = dict(kwargs)
        files = kwargs.pop("files", [])
        news = self.create(content_type=obj_type, object_id=obj.pk, **kwargs)
        news.files.set(files)
        return news
