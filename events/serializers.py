from rest_framework import serializers

from events.models import Event


class EventDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "text",
            "cover_url",
            "datetime_of_event",
            "datetime_created",
        ]


class EventsListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "short_text",
            "cover_url",
            "datetime_of_event",
        ]
