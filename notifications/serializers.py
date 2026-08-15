from rest_framework import serializers

from notifications.models import Notification
from users.models import CustomUser


class NotificationActorSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "first_name", "last_name", "avatar"]
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    actor = NotificationActorSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "category",
            "title",
            "message",
            "action_url",
            "read_at",
            "created_at",
            "actor",
        ]
        read_only_fields = fields


class NotificationListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    unread = serializers.BooleanField(default=False)
