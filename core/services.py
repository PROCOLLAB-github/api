from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from core.models import Like, View, Link

User = get_user_model()


def add_like(obj, user):
    obj_type = ContentType.objects.get_for_model(obj)
    like, is_created = Like.objects.get_or_create(
        content_type=obj_type, object_id=obj.id, user=user
    )
    return like


def remove_like(obj, user):
    obj_type = ContentType.objects.get_for_model(obj)
    Like.objects.filter(content_type=obj_type, object_id=obj.id, user=user).delete()


def is_fan(obj, user) -> bool:
    if not user.is_authenticated:
        return False
    obj_type = ContentType.objects.get_for_model(obj)
    likes = Like.objects.filter(content_type=obj_type, object_id=obj.id, user=user)
    return likes.exists()


def get_fans(obj):
    obj_type = ContentType.objects.get_for_model(obj)
    return User.objects.filter(likes__content_type=obj_type, likes__object_id=obj.id)


def get_likes_count(obj):
    obj_type = ContentType.objects.get_for_model(obj)
    return User.objects.filter(
        likes__content_type=obj_type, likes__object_id=obj.id
    ).count()


def set_like(obj, user, is_liked):
    if is_liked:
        add_like(obj, user)
    else:
        remove_like(obj, user)


def add_view(obj, user):
    # TODO: add docstring
    # TODO: add caching
    obj_type = ContentType.objects.get_for_model(obj)
    view, is_created = View.objects.get_or_create(
        content_type=obj_type, object_id=obj.id, user=user
    )
    return view


def remove_view(obj, user):
    obj_type = ContentType.objects.get_for_model(obj)
    View.objects.filter(content_type=obj_type, object_id=obj.id, user=user).delete()


def is_viewer(obj, user) -> bool:
    if not user.is_authenticated:
        return False
    obj_type = ContentType.objects.get_for_model(obj)
    views = View.objects.filter(content_type=obj_type, object_id=obj.id, user=user)
    return views.exists()


def get_viewers(obj):
    obj_type = ContentType.objects.get_for_model(obj)
    return User.objects.filter(views__content_type=obj_type, views__object_id=obj.id)


def get_views_count(obj):
    obj_type = ContentType.objects.get_for_model(obj)
    return User.objects.filter(
        views__content_type=obj_type, views__object_id=obj.id
    ).count()


def set_viewed(obj, user, is_viewed):
    if is_viewed:
        add_view(obj, user)
    else:
        remove_view(obj, user)


def add_link(obj, link: str):
    obj_type = ContentType.objects.get_for_model(obj)
    like, is_created = Link.objects.get_or_create(
        content_type=obj_type, object_id=obj.id, link=link
    )
    return like


def remove_link(obj, link):
    obj_type = ContentType.objects.get_for_model(obj)
    Like.objects.filter(content_type=obj_type, object_id=obj.id, link=link).delete()


def get_links(obj):
    obj_type = ContentType.objects.get_for_model(obj)
    return Link.objects.filter(content_type=obj_type, object_id=obj.id)
