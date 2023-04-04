from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import serializers
from taggit.serializers import TaggitSerializer, TagListSerializerField

from core.utils import get_user_online_cache_key
from events.models import Event
from users.serializers import MemberSerializer, KeySkillsField

USER = get_user_model()


class EventDetailSerializer(TaggitSerializer, serializers.ModelSerializer):
    tags = TagListSerializerField()

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "text",
            "cover_url",
            "datetime_of_event",
            "datetime_created",
            "tags",
            "tg_message_id"
            "website_url",
            "event_type",
            "prize",
            "favorites",
            "registered_users",
            "views",
            "likes",
        ]


class EventsListSerializer(TaggitSerializer, serializers.ModelSerializer):
    tags = TagListSerializerField()
    text = serializers.CharField(allow_null=False, write_only=True)

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "text",
            "short_text",
            "cover_url",
            "datetime_of_event",
            "tags",
            "event_type",
            "prize",
            "favorites",
        ]


class RegisteredUserListSerializer(serializers.ModelSerializer):
    member = MemberSerializer(required=False)
    key_skills = KeySkillsField(required=False)
    is_online = serializers.SerializerMethodField()

    @classmethod
    def get_is_online(cls, user: USER) -> bool:
        cache_key = get_user_online_cache_key(user)
        is_online = cache.get(cache_key, False)
        return is_online

    class Meta:
        model = USER
        fields = [
            "id",
            "user_type",
            "first_name",
            "last_name",
            "patronymic",
            "key_skills",
            "avatar",
            "speciality",
            "birthday",
            "is_online",
            "member",
        ]
