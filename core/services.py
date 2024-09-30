from PIL import Image
from io import BytesIO
import base64
from urllib.request import urlopen

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache

from core.constants import VIEWS_CACHING_TIMEOUT
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
    # todo: temp comment
    # likes_count = cache.get(f"likes_count_{obj_type}_{obj.id}")
    # if likes_count is None:
    #     likes_count = User.objects.filter(
    #         likes__content_type=obj_type, likes__object_id=obj.id
    #     ).count()
    #     # cache for LIKES_CACHING_TIMEOUT seconds
    #     cache.set(f"likes_count_{obj_type}_{obj.id}", likes_count, LIKES_CACHING_TIMEOUT)
    return User.objects.filter(
        likes__content_type=obj_type, likes__object_id=obj.id
    ).count()
    # return likes_count


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
    # cache this
    views_count = cache.get(f"views_count_{obj_type}_{obj.id}", None)
    if views_count is None:
        views_count = User.objects.filter(
            views__content_type=obj_type, views__object_id=obj.id
        ).count()
        # cache for VIEWS_CACHING_TIMEOUT seconds
        cache.set(f"views_count_{obj_type}_{obj.id}", views_count, VIEWS_CACHING_TIMEOUT)

    return views_count


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


class Base64ImageEncoder:
    """Encode image to base64."""
    BASE_QUALITY: int = 85

    def get_encoded_base64_from_url(self, url: str, max_width: int = 300) -> str:
        """
        Returns the full prepared base64 string pron url path.
        The original image is converted to JPEG with `max_width` and `BASE_QUALITY`% of quality.
        """
        response = urlopen(url)
        image_data = response.read()
        base64_image = self._get_compressed_image(image_data, max_width)
        return self._base64_full_string(base64_image)

    def get_encoded_base64_from_local_path(self, image_path: str) -> str:
        """Returns the full prepared base64 string pron url path."""
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        return self._base64_full_string(base64_image, image_path.split(".")[-1])

    def _base64_full_string(self, base_64_string: str, image_extension: str = "jpeg") -> str:
        return f"data:image/{image_extension};base64,{base_64_string}"

    def _get_compressed_image(self, image_data, max_width: int) -> str:
        """This step is necessary to reduce the size of the resulting file."""
        image = Image.open(BytesIO(image_data))
        image.thumbnail((max_width, max_width))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=self.BASE_QUALITY)
        base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return base64_image
