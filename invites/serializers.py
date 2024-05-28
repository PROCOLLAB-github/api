from rest_framework import serializers

from invites.models import Invite
from projects.serializers import ProjectListSerializer
from users.serializers import UserDetailSerializer


class InviteListSerializer(serializers.ModelSerializer[Invite]):
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


class InviteDetailSerializer(serializers.ModelSerializer[Invite]):
    user = UserDetailSerializer(many=False, read_only=True)
    project = ProjectListSerializer(many=False, read_only=True)

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
        read_only_fields = [
            "project",
            "user",
            "is_accepted",
            "datetime_created",
            "datetime_updated",
        ]
