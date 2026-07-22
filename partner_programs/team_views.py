from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.models import Team, TeamMember
from partner_programs.permissions import can_manage_team, can_view_team
from partner_programs.serializers import (
    TeamMemberSerializer,
    TeamSerializer,
    TeamTransferCaptainSerializer,
    TeamUpdateSerializer,
)
from partner_programs.services.application_team import ApplicationTeamServiceError
from partner_programs.services.team_management import (
    TeamManagementPermissionError,
    leave_team,
    remove_team_member,
    rename_team,
    transfer_team_captain,
)
from partner_programs.throttling import TeamMutationScopedRateThrottle


def _team_queryset():
    return Team.objects.select_related(
        "application",
        "application__program",
        "application__user",
        "captain",
    ).prefetch_related("members__user")


def _get_team(application_id: int) -> Team:
    return get_object_or_404(_team_queryset(), application_id=application_id)


def _team_response(team: Team, request) -> Response:
    team = _team_queryset().get(pk=team.pk)
    return Response(TeamSerializer(team, context={"request": request}).data)


def _raise_domain_error(exc: ApplicationTeamServiceError):
    if isinstance(exc, TeamManagementPermissionError):
        raise PermissionDenied(exc.detail, code=exc.code) from exc
    raise ValidationError({exc.field: exc.detail}, code=exc.code) from exc


class TeamDetailView(APIView):
    """Возвращает Team и позволяет капитану/staff изменить только название."""
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        team = _get_team(application_id)
        if not can_view_team(request.user, team):
            raise NotFound("Team not found.")
        return _team_response(team, request)

    def patch(self, request, application_id):
        team = _get_team(application_id)
        if not can_view_team(request.user, team):
            raise NotFound("Team not found.")
        if not can_manage_team(request.user, team):
            raise PermissionDenied(
                TeamManagementPermissionError.default_detail,
                code=TeamManagementPermissionError.code,
            )

        serializer = TeamUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            team = rename_team(
                team=team,
                actor=request.user,
                name=serializer.validated_data["name"],
            )
        except ApplicationTeamServiceError as exc:
            _raise_domain_error(exc)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return _team_response(team, request)

    def get_throttles(self):
        if self.request.method == "PATCH":
            self.throttle_scope = "team_rename"
            return [TeamMutationScopedRateThrottle()]
        return []


class TeamLeaveView(APIView):
    """Фиксирует самостоятельный выход обычного accepted-участника."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [TeamMutationScopedRateThrottle]
    throttle_scope = "team_leave"

    def post(self, request, application_id):
        team = _get_team(application_id)
        has_membership_history = TeamMember.objects.filter(
            team=team,
            user=request.user,
        ).exists()
        if not can_view_team(request.user, team) and not has_membership_history:
            raise NotFound("Team not found.")
        if not has_membership_history:
            raise PermissionDenied(
                TeamManagementPermissionError.default_detail,
                code=TeamManagementPermissionError.code,
            )
        try:
            member = leave_team(team=team, actor=request.user)
        except ApplicationTeamServiceError as exc:
            _raise_domain_error(exc)
        return Response(TeamMemberSerializer(member).data, status=status.HTTP_200_OK)


class TeamMemberRemoveView(APIView):
    """Фиксирует исключение участника капитаном или staff без удаления строки."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [TeamMutationScopedRateThrottle]
    throttle_scope = "team_remove_member"

    def post(self, request, application_id, member_id):
        team = _get_team(application_id)
        if not can_view_team(request.user, team):
            raise NotFound("Team not found.")
        if not can_manage_team(request.user, team):
            raise PermissionDenied(
                TeamManagementPermissionError.default_detail,
                code=TeamManagementPermissionError.code,
            )
        try:
            member = remove_team_member(
                team=team,
                actor=request.user,
                member_id=member_id,
            )
        except ApplicationTeamServiceError as exc:
            _raise_domain_error(exc)
        return Response(TeamMemberSerializer(member).data, status=status.HTTP_200_OK)


class TeamTransferCaptainView(APIView):
    """Передает капитанство через атомарный domain service."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [TeamMutationScopedRateThrottle]
    throttle_scope = "team_transfer_captain"

    def post(self, request, application_id):
        team = _get_team(application_id)
        if not can_view_team(request.user, team):
            raise NotFound("Team not found.")
        if not can_manage_team(request.user, team):
            raise PermissionDenied(
                TeamManagementPermissionError.default_detail,
                code=TeamManagementPermissionError.code,
            )
        serializer = TeamTransferCaptainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            team = transfer_team_captain(
                team=team,
                actor=request.user,
                member_id=serializer.validated_data["member_id"],
            )
        except ApplicationTeamServiceError as exc:
            _raise_domain_error(exc)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return _team_response(team, request)
