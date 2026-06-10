from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.services import is_fan, get_likes_count, get_views_count
from files.models import UserFile
from files.serializers import UserFileSerializer
from news.mapping import NewsMapping
from news.models import News


User = get_user_model()


class NewsInputSerializer(serializers.ModelSerializer[News]):
    files = serializers.PrimaryKeyRelatedField(
        queryset=UserFile.objects.none(),
        many=True,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            self.fields["files"].queryset = UserFile.objects.filter(user=user)

    class Meta:
        model = News
        fields = [
            "text",
            "files",
        ]


class NewsCreateSerializer(NewsInputSerializer):
    pass


class NewsUpdateSerializer(NewsInputSerializer):
    pass


class BaseNewsResponseSerializer(serializers.ModelSerializer[News]):
    views_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    image_address = serializers.SerializerMethodField()
    is_user_liked = serializers.SerializerMethodField()

    def get_name(self, obj):
        return NewsMapping.get_name(obj.content_object)

    def get_image_address(self, obj):
        return NewsMapping.get_image_address(obj.content_object)

    def get_views_count(self, obj):
        return get_views_count(obj)

    def get_likes_count(self, obj):
        return get_likes_count(obj)

    def get_is_user_liked(self, obj):
        user = self.context.get("user")
        if user:
            return is_fan(obj, user)
        return False


class BaseNewsListResponseSerializer(BaseNewsResponseSerializer):
    files = UserFileSerializer(many=True)

    class Meta:
        model = News
        fields = [
            "id",
            "name",
            "pin",
            "image_address",
            "text",
            "datetime_created",
            "views_count",
            "likes_count",
            "files",
            "is_user_liked",
        ]
        read_only_fields = ["pin"]


class ProjectNewsListResponseSerializer(BaseNewsListResponseSerializer):
    pass


class UserNewsListResponseSerializer(BaseNewsListResponseSerializer):
    pass


class ProgramNewsListResponseSerializer(BaseNewsListResponseSerializer):
    pass


class BaseNewsDetailResponseSerializer(BaseNewsResponseSerializer):

    class Meta:
        model = News
        fields = [
            "id",
            "name",
            "pin",
            "image_address",
            "text",
            "datetime_created",
            "datetime_updated",
            "views_count",
            "likes_count",
            "is_user_liked",
            "files",
        ]
        read_only_fields = ["pin"]


class ProjectNewsDetailResponseSerializer(BaseNewsDetailResponseSerializer):
    pass


class UserNewsDetailResponseSerializer(BaseNewsDetailResponseSerializer):
    pass


class ProgramNewsDetailResponseSerializer(BaseNewsDetailResponseSerializer):
    pass
