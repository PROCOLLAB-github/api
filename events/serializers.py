from rest_framework import serializers
from taggit.serializers import TaggitSerializer, TagListSerializerField

from events.models import Event


class EventDetailSerializer(serializers.ModelSerializer, TaggitSerializer):
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
