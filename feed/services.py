from django.contrib.contenttypes.models import ContentType

from core.models import Like
from feed.constants import SIGNALS_MODELS
from news.models import News
from users.models import CustomUser


def get_liked_news(user: CustomUser, queryset: list[News]) -> list[int]:
    obj_type = ContentType.objects.get_for_model(News)
    liked_news = Like.objects.filter(
        content_type=obj_type, object_id__in=[news.id for news in queryset], user=user
    ).values_list("object_id", flat=True)
    return liked_news


# signals services
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
