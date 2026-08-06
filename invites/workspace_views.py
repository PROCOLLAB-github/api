from django.contrib.auth import get_user_model
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from invites.models import Invite
from invites.workspace_serializers import (
    ProjectInvitationActionSerializer,
    ProjectInvitationCreateSerializer,
    ProjectInvitationSerializer,
)
from invites.workspace_services import (
    ProjectInvitationDuplicateError,
    ProjectInvitationNotOwnedError,
    ProjectInvitationNotPendingError,
    ProjectInvitationPermissionError,
    ProjectInvitationServiceError,
    ProjectInvitationTargetInvalidError,
    accept_project_invitation,
    can_manage_project_invitations,
    create_project_invitation,
    decline_project_invitation,
    revoke_project_invitation,
)
from projects.models import Project
from projects.workspace_selectors import filter_workspace_visible_projects

User = get_user_model()


class ProjectInvitationConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Приглашение уже обработано."
    default_code = "project_invitation_conflict"


def _invitation_queryset():
    return Invite.objects.select_related(
        "project",
        "project__leader",
        "user",
        "invited_by",
    )


def _get_visible_project(*, project_id: int, user) -> Project:
    projects = Project.objects.select_related("leader")
    projects = filter_workspace_visible_projects(projects, user=user)
    return get_object_or_404(projects, pk=project_id)


def _require_manager(user, project: Project) -> None:
    if not can_manage_project_invitations(user, project):
        raise PermissionDenied(
            ProjectInvitationPermissionError.default_detail,
            code=ProjectInvitationPermissionError.code,
        )


def _raise_domain_error(exc: ProjectInvitationServiceError):
    if isinstance(exc, ProjectInvitationPermissionError):
        raise PermissionDenied(exc.detail, code=exc.code) from exc
    if isinstance(exc, ProjectInvitationNotOwnedError):
        raise NotFound("Project invitation not found.") from exc
    if isinstance(
        exc, (ProjectInvitationDuplicateError, ProjectInvitationNotPendingError)
    ):
        raise ProjectInvitationConflict(
            {exc.field: [exc.detail]},
            code=exc.code,
        ) from exc
    raise ValidationError({exc.field: [exc.detail]}, code=exc.code) from exc


def _validate_empty_action_payload(data) -> None:
    serializer = ProjectInvitationActionSerializer(data=data)
    serializer.is_valid(raise_exception=True)


class ProjectInvitationListCreateView(APIView):
    """Возвращает историю приглашений Project и создает pending-запись."""

    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        project = _get_visible_project(project_id=project_id, user=request.user)
        _require_manager(request.user, project)
        invitations = (
            _invitation_queryset()
            .filter(project=project)
            .order_by(
                "-datetime_created",
                "-id",
            )
        )
        return Response(ProjectInvitationSerializer(invitations, many=True).data)

    def post(self, request, project_id):
        project = _get_visible_project(project_id=project_id, user=request.user)
        _require_manager(request.user, project)
        serializer = ProjectInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recipient = User.objects.filter(
            pk=serializer.validated_data["recipient_id"],
            is_active=True,
        ).first()
        if recipient is None:
            _raise_domain_error(ProjectInvitationTargetInvalidError())

        try:
            invitation = create_project_invitation(
                project_id=project.pk,
                actor=request.user,
                recipient=recipient,
                role=serializer.validated_data.get("role"),
                specialization=serializer.validated_data.get("specialization"),
                motivational_letter=serializer.validated_data.get("message"),
            )
        except ProjectInvitationServiceError as exc:
            _raise_domain_error(exc)
        invitation = _invitation_queryset().get(pk=invitation.pk)
        return Response(
            ProjectInvitationSerializer(invitation).data,
            status=status.HTTP_201_CREATED,
        )


class IncomingProjectInvitationListView(APIView):
    """Возвращает только историю приглашений текущего пользователя."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        invitations = (
            _invitation_queryset()
            .filter(user=request.user)
            .annotate(
                pending_order=Case(
                    When(
                        is_accepted__isnull=True,
                        is_revoked=False,
                        then=Value(0),
                    ),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .order_by("pending_order", "-datetime_created", "-id")
        )
        return Response(ProjectInvitationSerializer(invitations, many=True).data)


class ProjectInvitationAcceptView(APIView):
    """Принимает pending-приглашение только его получателем."""

    permission_classes = [IsAuthenticated]

    def post(self, request, invitation_id):
        _validate_empty_action_payload(request.data)
        invitation = get_object_or_404(
            _invitation_queryset().filter(user=request.user),
            pk=invitation_id,
        )
        try:
            invitation = accept_project_invitation(
                invitation_id=invitation.pk,
                actor=request.user,
            )
        except ProjectInvitationServiceError as exc:
            _raise_domain_error(exc)
        invitation = _invitation_queryset().get(pk=invitation.pk)
        return Response(ProjectInvitationSerializer(invitation).data)


class ProjectInvitationDeclineView(APIView):
    """Отклоняет pending-приглашение только его получателем."""

    permission_classes = [IsAuthenticated]

    def post(self, request, invitation_id):
        _validate_empty_action_payload(request.data)
        invitation = get_object_or_404(
            _invitation_queryset().filter(user=request.user),
            pk=invitation_id,
        )
        try:
            invitation = decline_project_invitation(
                invitation_id=invitation.pk,
                actor=request.user,
            )
        except ProjectInvitationServiceError as exc:
            _raise_domain_error(exc)
        invitation = _invitation_queryset().get(pk=invitation.pk)
        return Response(ProjectInvitationSerializer(invitation).data)


class ProjectInvitationRevokeView(APIView):
    """Отзывает pending-приглашение через project-scoped URL без удаления истории."""

    permission_classes = [IsAuthenticated]

    def post(self, request, project_id, invitation_id):
        _validate_empty_action_payload(request.data)
        project = _get_visible_project(project_id=project_id, user=request.user)
        _require_manager(request.user, project)
        invitation = get_object_or_404(
            _invitation_queryset().filter(project=project),
            pk=invitation_id,
        )
        try:
            invitation = revoke_project_invitation(
                invitation_id=invitation.pk,
                actor=request.user,
            )
        except ProjectInvitationServiceError as exc:
            _raise_domain_error(exc)
        invitation = _invitation_queryset().get(pk=invitation.pk)
        return Response(ProjectInvitationSerializer(invitation).data)
