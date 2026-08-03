from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from projects.pagination import ProjectsPagination
from projects.workspace_selectors import (
    get_project_catalog_queryset,
    get_user_projects_queryset,
    get_workspace_project_queryset,
)
from projects.workspace_serializers import (
    ProjectWorkspaceCreateSerializer,
    ProjectWorkspaceDetailSerializer,
    ProjectWorkspaceListSerializer,
    ProjectWorkspaceUpdateSerializer,
)


def _parse_industry_id(raw_value):
    if raw_value in (None, ""):
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"industry": "Укажите корректный идентификатор отрасли."}
        ) from exc
    if value <= 0:
        raise ValidationError({"industry": "Укажите корректный идентификатор отрасли."})
    return value


class ProjectCatalogView(generics.ListAPIView):
    """Публичный каталог опубликованных проектов для авторизованного React-клиента."""

    permission_classes = [IsAuthenticated]
    serializer_class = ProjectWorkspaceListSerializer
    pagination_class = ProjectsPagination

    def get_queryset(self):
        return get_project_catalog_queryset(
            user=self.request.user,
            search=self.request.query_params.get("search"),
            industry_id=_parse_industry_id(self.request.query_params.get("industry")),
        )


class MyProjectsView(generics.ListAPIView):
    """Проекты, которыми пользователь руководит или в которых участвует."""

    permission_classes = [IsAuthenticated]
    serializer_class = ProjectWorkspaceListSerializer
    pagination_class = ProjectsPagination

    def get_queryset(self):
        return get_user_projects_queryset(
            user=self.request.user,
            search=self.request.query_params.get("search"),
        )


class ProjectWorkspaceCreateView(APIView):
    """Создает самостоятельный приватный черновик для React workspace."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ProjectWorkspaceCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        project = serializer.save()
        created_project = get_workspace_project_queryset(user=request.user).get(
            pk=project.pk
        )
        response_serializer = ProjectWorkspaceDetailSerializer(
            created_project,
            context={"request": request},
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class ProjectWorkspaceDetailView(APIView):
    """Безопасная карточка Project и ограниченное редактирование лидером."""

    permission_classes = [IsAuthenticated]

    def get_object(self, request, project_id):
        queryset = get_workspace_project_queryset(user=request.user)
        if not (request.user.is_staff or request.user.is_superuser):
            queryset = queryset.filter(
                Q(draft=False, is_public=True)
                | Q(leader=request.user)
                | Q(collaborator__user=request.user)
            ).distinct()
        return get_object_or_404(queryset, pk=project_id)

    def get(self, request, project_id):
        project = self.get_object(request, project_id)
        serializer = ProjectWorkspaceDetailSerializer(
            project,
            context={"request": request},
        )
        return Response(serializer.data)

    def patch(self, request, project_id):
        project = self.get_object(request, project_id)
        if not (
            request.user.is_staff
            or request.user.is_superuser
            or project.leader_id == request.user.pk
        ):
            raise PermissionDenied("Редактировать проект может только руководитель.")

        serializer = ProjectWorkspaceUpdateSerializer(
            project,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Повторная выборка возвращает тот же полный контракт, что и GET,
        # включая вычисленные права и связанные активности.
        updated_project = self.get_object(request, project_id)
        response_serializer = ProjectWorkspaceDetailSerializer(
            updated_project,
            context={"request": request},
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)
