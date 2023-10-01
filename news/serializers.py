from rest_framework import serializers

from core.services import is_fan, get_likes_count, get_views_count
from files.serializers import UserFileSerializer
from news.models import News


class NewsListSerializer(serializers.ModelSerializer):
    views_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    image_address = serializers.SerializerMethodField()
    is_user_liked = serializers.SerializerMethodField()
    files = UserFileSerializer(many=True)

    def get_name(self, obj):
        return obj.content_object.name

    def get_image_address(self, obj):
        return obj.content_object.image_address

    def get_views_count(self, obj):
        return get_views_count(obj)

    def get_likes_count(self, obj):
        return get_likes_count(obj)

    def get_is_user_liked(self, obj):
        # fixme: move this method to helpers somewhere
        user = self.context.get("user")
        if user:
            return is_fan(obj, user)
        return False

    class Meta:
        model = News
        fields = [
            "id",
            "name",
            "image_address",
            "text",
            "datetime_created",
            "views_count",
            "likes_count",
            "files",
            "is_user_liked",
        ]


class NewsDetailSerializer(serializers.ModelSerializer):
    views_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    image_address = serializers.SerializerMethodField()
    is_user_liked = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.content_object.name

    def get_image_address(self, obj):
        return obj.content_object.image_address

    def get_views_count(self, obj):
        return get_views_count(obj)

    def get_likes_count(self, obj):
        return get_likes_count(obj)

    def get_is_user_liked(self, obj):
        user = self.context.get("user")
        if user:
            return is_fan(obj, user)
        return False

    class Meta:
        model = News
        fields = [
            "id",
            "name",
            "image_address",
            "text",
            "datetime_created",
            "datetime_updated",
            "views_count",
            "likes_count",
            "is_user_liked",
            "files",
        ]
