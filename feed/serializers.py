from rest_framework import serializers

from core.services import get_views_count, get_likes_count
from feed.mapping import CONTENT_OBJECT_MAPPING, CONTENT_OBJECT_SERIALIZER_MAPPING
from files.serializers import UserFileSerializer
from news.mapping import NewsMapping
from news.models import News
from projects.models import Project
from users.models import CustomUser


class NewsFeedListSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    image_address = serializers.SerializerMethodField()
    is_user_liked = serializers.SerializerMethodField()
    files = UserFileSerializer(many=True)
    views_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    content_object = serializers.SerializerMethodField()
    type_model = serializers.SerializerMethodField()

    def get_type_model(self, obj) -> str:
        model_type = CONTENT_OBJECT_MAPPING[obj.content_type.model]
        if obj.text != "" and model_type == "project":
            return "news"
        return model_type

    def get_content_object(self, obj) -> dict:
        type_model = obj.content_type.model
        if obj.text != "" and self.get_type_model(obj) == "project":
            type_model = "news"
        serializer = CONTENT_OBJECT_SERIALIZER_MAPPING[type_model](obj.content_object)
        return serializer.data

    def get_views_count(self, obj):
        return get_views_count(obj)

    def get_likes_count(self, obj):
        return get_likes_count(obj)

    def get_name(self, obj):
        if obj.content_type.model == CustomUser.__name__.lower():
            return f"{obj.content_object.first_name} {obj.content_object.last_name}"
        elif obj.text != "" and obj.content_type.model == Project.__name__.lower():
            return f"{obj.content_object.name}"

    def get_image_address(self, obj):
        return NewsMapping.get_image_address(obj.content_object)

    def get_is_user_liked(self, obj):
        return obj.id in self.context.get("liked_news")

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
            "content_object",
            "type_model",
        ]
        read_only_fields = ["views_count", "likes_count", "type_model"]
