from django.contrib.auth import get_user_model
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.models import Team, TeamInvite
from partner_programs.permissions import can_manage_team, can_view_team
from partner_programs.serializers import (
    MyTeamInviteSerializer,
    TeamInviteCreateSerializer,
    TeamInviteSerializer,
)
from partner_programs.services.application_team import ApplicationTeamServiceError
from partner_programs.services.team_invites import (
    TeamInviteNotOwnedError,
    TeamInvitePermissionError,
    TeamInviteTargetInvalidError,
    accept_team_invite,
    create_team_invite,
    decline_team_invite,
    revoke_team_invite,
)
from partner_programs.throttling import TeamInviteMutationScopedRateThrottle

User = get_user_model()


def _team_queryset():
    return Team.objects.select_related(
        "application",
        "application__program",
        "application__user",
        "captain",
    )


def _invite_queryset():
    return TeamInvite.objects.select_related(
        "team",
        "team__application",
        "team__application__program",
        "team__captain",
        "user",
        "invited_by",
    )


def _get_team(application_id: int) -> Team:
    return get_object_or_404(_team_queryset(), application_id=application_id)


def _get_invite(invite_id: int) -> TeamInvite:
    return get_object_or_404(_invite_queryset(), pk=invite_id)


def _raise_domain_error(exc: ApplicationTeamServiceError):
    if isinstance(exc, (TeamInvitePermissionError, TeamInviteNotOwnedError)):
        raise PermissionDenied(exc.detail, code=exc.code) from exc
    raise ValidationError({exc.field: exc.detail}, code=exc.code) from exc


def _require_invite_manager(user, team: Team) -> None:
    # Незнакомому пользователю скрываем существование Team; участник и manager
    # знают команду, но получают явный запрет на закрытый список приглашений.
    if not can_view_team(user, team):
        raise NotFound("Team not found.")
    if not can_manage_team(user, team):
        raise PermissionDenied(
            TeamInvitePermissionError.default_detail,
            code=TeamInvitePermissionError.code,
        )


class TeamInviteListCreateView(APIView):
    """Возвращает историю приглашений и создает pending для капитана/staff."""

    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        team = _get_team(application_id)
        _require_invite_manager(request.user, team)
        invites = _invite_queryset().filter(team=team).order_by("-created_at")
        return Response(TeamInviteSerializer(invites, many=True).data)

    def post(self, request, application_id):
        team = _get_team(application_id)
        _require_invite_manager(request.user, team)
        serializer = TeamInviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = User.objects.filter(pk=serializer.validated_data["user_id"]).first()
        if target is None:
            _raise_domain_error(TeamInviteTargetInvalidError())

        try:
            result = create_team_invite(
                team=team,
                actor=request.user,
                target=target,
            )
        except ApplicationTeamServiceError as exc:
            _raise_domain_error(exc)

        response_status = (
            status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        )
        return Response(
            TeamInviteSerializer(result.invite).data,
            status=response_status,
        )

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "team_invite_create"
            return [TeamInviteMutationScopedRateThrottle()]
        return []


class MyTeamInviteListView(APIView):
    """Возвращает только приглашения текущего пользователя: pending первыми."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        invites = (
            _invite_queryset()
            .filter(user=request.user)
            .annotate(
                pending_order=Case(
                    When(status=TeamInvite.STATUS_PENDING, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .order_by("pending_order", "-created_at")
        )
        return Response(MyTeamInviteSerializer(invites, many=True).data)


class TeamInviteAcceptView(APIView):
    """Принимает приглашение адресатом через атомарный domain service."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [TeamInviteMutationScopedRateThrottle]
    throttle_scope = "team_invite_accept"

    def post(self, request, invite_id):
        invite = _get_invite(invite_id)
        if invite.user_id != request.user.pk:
            if can_manage_team(request.user, invite.team):
                raise PermissionDenied(
                    TeamInviteNotOwnedError.default_detail,
                    code=TeamInviteNotOwnedError.code,
                )
            raise NotFound("Team invite not found.")
        try:
            invite = accept_team_invite(invite=invite, actor=request.user)
        except ApplicationTeamServiceError as exc:
            _raise_domain_error(exc)
        return Response(MyTeamInviteSerializer(invite).data)


class TeamInviteDeclineView(APIView):
    """Отклоняет приглашение адресатом без создания TeamMember."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [TeamInviteMutationScopedRateThrottle]
    throttle_scope = "team_invite_decline"

    def post(self, request, invite_id):
        invite = _get_invite(invite_id)
        if invite.user_id != request.user.pk:
            if can_manage_team(request.user, invite.team):
                raise PermissionDenied(
                    TeamInviteNotOwnedError.default_detail,
                    code=TeamInviteNotOwnedError.code,
                )
            raise NotFound("Team invite not found.")
        try:
            invite = decline_team_invite(invite=invite, actor=request.user)
        except ApplicationTeamServiceError as exc:
            _raise_domain_error(exc)
        return Response(MyTeamInviteSerializer(invite).data)


class TeamInviteRevokeView(APIView):
    """Отзывает приглашение капитаном команды или staff."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [TeamInviteMutationScopedRateThrottle]
    throttle_scope = "team_invite_revoke"

    def post(self, request, invite_id):
        invite = _get_invite(invite_id)
        _require_invite_manager(request.user, invite.team)
        try:
            invite = revoke_team_invite(invite=invite, actor=request.user)
        except ApplicationTeamServiceError as exc:
            _raise_domain_error(exc)
        return Response(TeamInviteSerializer(invite).data)
