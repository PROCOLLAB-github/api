from rest_framework import serializers

from invites.models import Invite
from projects import team_service
from projects.serializers import ProjectListSerializer
from users.models import CustomUser
from users.serializers import UserDetailSerializer


class InviteSenderSerializer(serializers.ModelSerializer[CustomUser]):
    class Meta:
        model = CustomUser
        fields = [
            "id",
            "first_name",
            "last_name",
            "patronymic",
            "avatar",
        ]


class InviteListSerializer(serializers.ModelSerializer[Invite]):
    class Meta:
        model = Invite
        fields = [
            "id",
            "project",
            "user",
            "motivational_letter",
            "role",
            "specialization",
            "is_accepted",
        ]
        read_only_fields = ["is_accepted"]
        # Unique conflict проверяется service под lock и возвращает одинаковый 409.
        validators = []

    def create(self, validated_data):
        return team_service.create_invite(
            project_id=validated_data.pop("project").pk,
            user_id=validated_data.pop("user").pk,
            actor=self.context["request"].user,
            **validated_data,
        )


class InviteDetailSerializer(serializers.ModelSerializer[Invite]):
    user = UserDetailSerializer(many=False, read_only=True)
    project = ProjectListSerializer(many=False, read_only=True)
    sender = InviteSenderSerializer(source="project.leader", read_only=True)
    specialization = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=100
    )

    class Meta:
        model = Invite
        fields = [
            "id",
            "project",
            "user",
            "sender",
            "motivational_letter",
            "role",
            "specialization",
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

    def update(self, instance, validated_data):
        return team_service.edit_pending_invite(
            invite_id=instance.pk,
            actor=self.context["request"].user,
            **validated_data,
        )
