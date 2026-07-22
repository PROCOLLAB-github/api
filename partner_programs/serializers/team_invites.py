from rest_framework import serializers

from partner_programs.models import Application, Team, TeamInvite
from partner_programs.serializers.teams import TeamUserSerializer


class TeamInviteCreateSerializer(serializers.Serializer):
    """Принимает только публичный идентификатор зарегистрированного пользователя."""

    user_id = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        unsupported = set(self.initial_data).difference({"user_id"})
        if unsupported:
            raise serializers.ValidationError(
                {
                    field: "This field is read-only."
                    for field in sorted(unsupported)
                }
            )
        return attrs


class TeamInviteCandidateQuerySerializer(serializers.Serializer):
    """Не допускает пустой или слишком широкий поиск пользователей."""

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


class TeamInviteSerializer(serializers.ModelSerializer):
    """Безопасное представление приглашения для капитана и staff."""

    user = TeamUserSerializer(read_only=True)
    invited_by = TeamUserSerializer(read_only=True)

    class Meta:
        model = TeamInvite
        fields = (
            "id",
            "user",
            "invited_by",
            "status",
            "resolved_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TeamInviteTeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ("id", "name")
        read_only_fields = fields


class TeamInviteProgramSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


def _invite_is_actionable(invite: TeamInvite) -> bool:
    """Учитывает status приглашения, draft заявки и отдельный дедлайн."""
    application = invite.team.application
    return (
        invite.status == TeamInvite.STATUS_PENDING
        and application.status == Application.STATUS_DRAFT
        and not application.program.is_application_deadline_passed()
    )


class MyTeamInviteSerializer(serializers.ModelSerializer):
    """Показывает адресату контекст приглашения без приватных полей профиля."""

    team = TeamInviteTeamSerializer(read_only=True)
    application_id = serializers.IntegerField(
        source="team.application_id",
        read_only=True,
    )
    captain = TeamUserSerializer(source="team.captain", read_only=True)
    program = TeamInviteProgramSerializer(
        source="team.application.program",
        read_only=True,
    )
    can_accept = serializers.SerializerMethodField()
    can_decline = serializers.SerializerMethodField()

    class Meta:
        model = TeamInvite
        fields = (
            "id",
            "status",
            "team",
            "application_id",
            "captain",
            "program",
            "created_at",
            "resolved_at",
            "can_accept",
            "can_decline",
        )
        read_only_fields = fields

    def get_can_accept(self, invite: TeamInvite) -> bool:
        return _invite_is_actionable(invite)

    def get_can_decline(self, invite: TeamInvite) -> bool:
        return _invite_is_actionable(invite)
