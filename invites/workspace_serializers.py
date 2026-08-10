from rest_framework import serializers

from invites.models import Invite
from projects.models import Project
from users.models import CustomUser


class ProjectInvitationCandidateQuerySerializer(serializers.Serializer):
    """Проверяет обязательный узкий поисковый запрос кандидатов."""

    q = serializers.CharField(  # noqa: VNE001 — имя закреплено API-контрактом.
        required=True,
        trim_whitespace=True,
        min_length=3,
        max_length=100,
        error_messages={
            "required": "Укажите поисковый запрос.",
            "blank": "Укажите поисковый запрос.",
            "min_length": "Введите не менее 3 символов.",
            "max_length": "Введите не более 100 символов.",
        },
    )


class ProjectInvitationCandidateSerializer(serializers.ModelSerializer):
    """Возвращает только публичный минимум профиля кандидата."""

    display_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ("id", "display_name", "avatar")
        read_only_fields = fields

    def get_display_name(self, user: CustomUser) -> str:
        """Формирует имя без fallback на закрытый email пользователя."""
        return user.get_full_name().strip()


class ProjectInvitationCreateSerializer(serializers.Serializer):
    """Принимает пользователя и необязательные данные будущего Collaborator."""

    recipient_id = serializers.IntegerField(min_value=1)
    role = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=128,
    )
    specialization = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=100,
    )
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=4096,
    )

    def validate(self, attrs):
        unsupported = set(self.initial_data).difference(self.fields)
        if unsupported:
            raise serializers.ValidationError(
                {
                    field: "Это поле нельзя передавать при создании приглашения."
                    for field in sorted(unsupported)
                }
            )
        return attrs


class ProjectInvitationActionSerializer(serializers.Serializer):
    """Запрещает подмену Project, получателя или статуса в action payload."""

    def validate(self, attrs):
        if self.initial_data:
            raise serializers.ValidationError(
                {
                    field: "Это поле нельзя передавать для данного действия."
                    for field in sorted(self.initial_data)
                }
            )
        return attrs


class ProjectInvitationUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ("id", "first_name", "last_name", "avatar")
        read_only_fields = fields


class ProjectInvitationProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ("id", "name", "draft", "is_public")
        read_only_fields = fields


class ProjectInvitationSerializer(serializers.ModelSerializer):
    """Не раскрывает email и приватные поля профилей участников Project."""

    project = ProjectInvitationProjectSerializer(read_only=True)
    sender = serializers.SerializerMethodField()
    recipient = ProjectInvitationUserSerializer(source="user", read_only=True)
    status = serializers.CharField(read_only=True)
    message = serializers.CharField(
        source="motivational_letter",
        read_only=True,
        allow_null=True,
    )
    processed_at = serializers.DateTimeField(source="resolved_at", read_only=True)
    created_at = serializers.DateTimeField(source="datetime_created", read_only=True)
    updated_at = serializers.DateTimeField(source="datetime_updated", read_only=True)

    class Meta:
        model = Invite
        fields = (
            "id",
            "project",
            "sender",
            "recipient",
            "status",
            "role",
            "specialization",
            "message",
            "created_at",
            "processed_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_sender(self, invitation: Invite):
        sender = invitation.invited_by or invitation.project.leader
        return ProjectInvitationUserSerializer(sender).data
