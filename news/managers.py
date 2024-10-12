from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.query import QuerySet
import typing

if typing.TYPE_CHECKING:
    from news.models import News


class NewsManager(models.Manager):
    def get_news(self, obj: models.Model) -> QuerySet["News"]:
        obj_type = ContentType.objects.get_for_model(obj)
        return self.get_queryset().filter(content_type=obj_type, object_id=obj.pk)

    def add_news(self, obj: models.Model, **kwargs) -> "News":
        obj_type = ContentType.objects.get_for_model(obj)
        kwargs = dict(kwargs)
        files = kwargs.pop("files", [])
        news = self.create(content_type=obj_type, object_id=obj.pk, **kwargs)
        news.files.set(files)
        return news
