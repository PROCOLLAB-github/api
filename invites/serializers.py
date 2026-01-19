from django.apps import apps
from rest_framework import serializers

from invites.models import Invite
from projects.models import Collaborator
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

    def validate(self, attrs):
        project = attrs["project"]
        user = attrs["user"]

        if project.leader_id == user.id:
            raise serializers.ValidationError(
                {"user": "Пользователь уже является лидером проекта."}
            )

        if Collaborator.objects.filter(project=project, user=user).exists():
            raise serializers.ValidationError(
                {"user": "Пользователь уже состоит в проекте."}
            )

        if Invite.objects.filter(
            project=project, user=user, is_accepted__isnull=True
        ).exists():
            raise serializers.ValidationError(
                {"user": "У пользователя уже есть активное приглашение в этот проект."}
            )

        link = project.program_links.select_related("partner_program").first()
        if link:
            PartnerProgramUserProfile = apps.get_model(
                "partner_programs", "PartnerProgramUserProfile"
            )
            is_participant = PartnerProgramUserProfile.objects.filter(
                user_id=user.id,
                partner_program_id=link.partner_program_id,
            ).exists()
            if not is_participant:
                raise serializers.ValidationError(
                    {
                        "user": (
                            "Нельзя пригласить пользователя: проект относится к программе, "
                            "а пользователь не является её участником."
                        )
                    }
                )

        return attrs


class InviteDetailSerializer(serializers.ModelSerializer[Invite]):
    user = UserDetailSerializer(many=False, read_only=True)
    project = ProjectListSerializer(many=False, read_only=True)
    sender = InviteSenderSerializer(source="project.leader", read_only=True)
    specialization = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
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
