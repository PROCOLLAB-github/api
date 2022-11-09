from rest_framework import serializers

from invites.models import Invite
from users.serializers import UserDetailSerializer


class InviteListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invite
        fields = [
            "id",
            "project",
            "user",
            "motivational_letter",
            "role",
            "is_accepted",
        ]


class InviteDetailSerializer(serializers.ModelSerializer):
    user = UserDetailSerializer(many=False, read_only=True)

    class Meta:
        model = Invite
        fields = [
            "id",
            "project",
            "user",
            "motivational_letter",
            "role",
            "is_accepted",
            "datetime_created",
            "datetime_updated",
        ]
