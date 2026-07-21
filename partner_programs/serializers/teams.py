from rest_framework import serializers

from partner_programs.models import Application, Team, TeamMember
from partner_programs.permissions import can_manage_team, is_accepted_team_member
from users.models import CustomUser


class TeamUserSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ("id", "display_name", "avatar")
        read_only_fields = fields

    def get_display_name(self, user: CustomUser) -> str:
        """Возвращает безопасное имя без email и закрытых полей профиля."""
        return user.get_full_name().strip()


class TeamMemberSerializer(serializers.ModelSerializer):
    user = TeamUserSerializer(read_only=True)

    class Meta:
        model = TeamMember
        fields = (
            "id",
            "user",
            "role",
            "status",
            "joined_at",
            "created_at",
        )
        read_only_fields = fields


def _current_user_role(team: Team, request):
    """Не выдает роль по приглашенному или историческому membership."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None
    member = team.members.filter(
        user=user,
        status=TeamMember.STATUS_ACCEPTED,
    ).first()
    return member.role if member else None


def _team_is_mutable(team: Team) -> bool:
    """Учитывает статус заявки и отдельный deadline без legacy fallback."""
    return (
        team.application.status == Application.STATUS_DRAFT
        and not team.application.program.is_application_deadline_passed()
    )


class ApplicationTeamSummarySerializer(serializers.ModelSerializer):
    captain_id = serializers.IntegerField(read_only=True)
    accepted_members_count = serializers.SerializerMethodField()
    current_user_role = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = (
            "id",
            "name",
            "captain_id",
            "accepted_members_count",
            "current_user_role",
        )
        read_only_fields = fields

    def get_accepted_members_count(self, team: Team) -> int:
        return team.members.filter(status=TeamMember.STATUS_ACCEPTED).count()

    def get_current_user_role(self, team: Team):
        return _current_user_role(team, self.context.get("request"))


class TeamSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(read_only=True)
    program_id = serializers.IntegerField(source="application.program_id", read_only=True)
    captain = TeamUserSerializer(read_only=True)
    members = serializers.SerializerMethodField()
    accepted_members_count = serializers.SerializerMethodField()
    team_min_size = serializers.IntegerField(
        source="application.program.team_min_size",
        read_only=True,
        allow_null=True,
    )
    team_max_size = serializers.IntegerField(
        source="application.program.team_max_size",
        read_only=True,
        allow_null=True,
    )
    current_user_role = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_manage_members = serializers.SerializerMethodField()
    can_leave = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = (
            "id",
            "application_id",
            "program_id",
            "name",
            "captain",
            "members",
            "accepted_members_count",
            "team_min_size",
            "team_max_size",
            "current_user_role",
            "can_edit",
            "can_manage_members",
            "can_leave",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_members(self, team: Team):
        members = list(team.members.select_related("user").all())

        def sort_key(member: TeamMember):
            if (
                member.role == TeamMember.ROLE_CAPTAIN
                and member.status == TeamMember.STATUS_ACCEPTED
            ):
                rank = 0
            elif member.status == TeamMember.STATUS_ACCEPTED:
                rank = 1
            else:
                rank = 2
            return rank, member.created_at, member.pk

        members.sort(key=sort_key)
        return TeamMemberSerializer(members, many=True).data

    def get_accepted_members_count(self, team: Team) -> int:
        return team.members.filter(status=TeamMember.STATUS_ACCEPTED).count()

    def get_current_user_role(self, team: Team):
        return _current_user_role(team, self.context.get("request"))

    def get_can_edit(self, team: Team) -> bool:
        request = self.context.get("request")
        return bool(
            request
            and can_manage_team(request.user, team)
            and _team_is_mutable(team)
        )

    def get_can_manage_members(self, team: Team) -> bool:
        return self.get_can_edit(team)

    def get_can_leave(self, team: Team) -> bool:
        request = self.context.get("request")
        if not request or not _team_is_mutable(team):
            return False
        user = request.user
        if not is_accepted_team_member(user, team):
            return False
        return team.members.filter(
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
        ).exists()


class TeamUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        unsupported = set(self.initial_data).difference({"name"})
        if unsupported:
            raise serializers.ValidationError(
                {
                    field: "This field is read-only."
                    for field in sorted(unsupported)
                }
            )
        return attrs


class TeamTransferCaptainSerializer(serializers.Serializer):
    member_id = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        unsupported = set(self.initial_data).difference({"member_id"})
        if unsupported:
            raise serializers.ValidationError(
                {
                    field: "This field is read-only."
                    for field in sorted(unsupported)
                }
            )
        return attrs
