from django.contrib.auth import get_user_model
from django.forms import model_to_dict
from rest_framework import serializers

from core.services import is_fan, get_likes_count, get_views_count
from files.serializers import UserFileSerializer
from news.mapping import NewsMapping
from news.models import News

from partner_programs.serializers import PartnerProgramListSerializer
from projects.models import Project
from projects.serializers import ProjectListSerializer
from users.models import CustomUser
from users.serializers import UserFeedSerializer
from vacancy.models import Vacancy
from vacancy.serializers import VacancyDetailSerializer

User = get_user_model()


class NewsListCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = News
        fields = [
            "text",
            "files",
        ]


class NewsListSerializer(serializers.ModelSerializer):
    views_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    image_address = serializers.SerializerMethodField()
    is_user_liked = serializers.SerializerMethodField()
    files = UserFileSerializer(many=True)

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


class NewsFeedListSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    image_address = serializers.SerializerMethodField()
    is_user_liked = serializers.SerializerMethodField()
    files = UserFileSerializer(many=True)
    views_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    content_object = serializers.SerializerMethodField()
    type_model = serializers.SerializerMethodField()

    def get_type_model(self, obj):
        if obj.content_type.model == Project.__name__.lower():
            return "project"
        elif obj.content_type.model == CustomUser.__name__.lower():
            return "news"
        elif obj.content_type.model == "partnerprogram":
            return None
        elif obj.content_type.model == Vacancy.__name__.lower():
            return "vacancy"

    def get_content_object(self, obj):
        if obj.content_type.model == Project.__name__.lower():
            serialized_obj = ProjectListSerializer(instance=obj.content_object, data={})
            serialized_obj.is_valid()
            return serialized_obj.data
        elif obj.content_type.model == CustomUser.__name__.lower():
            serialized_obj = UserFeedSerializer(
                instance=obj.content_object, data=model_to_dict(obj.content_object)
            )
            serialized_obj.is_valid()
            return serialized_obj.data
        elif obj.content_type.model == "partnerprogram":
            serialized_obj = PartnerProgramListSerializer(obj.content_object)
            return serialized_obj.data
        elif obj.content_type.model == Vacancy.__name__.lower():
            serialized_obj = VacancyDetailSerializer(obj.content_object)
            return serialized_obj.data

    def get_views_count(self, obj):
        return get_views_count(obj)

    def get_likes_count(self, obj):
        return get_likes_count(obj)

    def get_name(self, obj):
        if obj.content_type.model == CustomUser.__name__.lower():
            return f"{obj.content_object.first_name} {obj.content_object.last_name}"

    def get_image_address(self, obj):
        return NewsMapping.get_image_address(obj.content_object)

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
            "views_count",
            "likes_count",
            "files",
            "is_user_liked",
            "content_object",
            "type_model",
        ]
        read_only_fields = ["views_count", "likes_count", "type_model"]


class NewsDetailSerializer(serializers.ModelSerializer):
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
