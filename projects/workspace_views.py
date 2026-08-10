from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from projects.models import Project
from projects.pagination import ProjectsPagination
from projects.workspace_selectors import (
    filter_workspace_visible_projects,
    get_project_catalog_queryset,
    get_user_projects_queryset,
    get_workspace_project_queryset,
    get_workspace_subscription_queryset,
)
from projects.workspace_serializers import (
    ProjectSubscriptionActionSerializer,
    ProjectSubscriptionStateSerializer,
    ProjectWorkspaceCreateSerializer,
    ProjectWorkspaceDetailSerializer,
    ProjectWorkspaceListSerializer,
    ProjectWorkspaceUpdateSerializer,
)
from projects.workspace_subscription_services import (
    set_workspace_project_subscription,
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
        queryset = filter_workspace_visible_projects(queryset, user=request.user)
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


class ProjectWorkspaceSubscriptionView(APIView):
    """Возвращает и идемпотентно меняет подписку текущего пользователя."""

    permission_classes = [IsAuthenticated]

    def get_object(self, request, project_id):
        queryset = get_workspace_subscription_queryset(user=request.user)
        project = queryset.filter(pk=project_id).first()
        if project is None:
            raise NotFound("Проект не найден.")
        return project

    def get(self, request, project_id):
        project = self.get_object(request, project_id)
        return Response(ProjectSubscriptionStateSerializer(project).data)

    def update_subscription(self, request, project_id, *, is_subscribed):
        """Проверяет пустой payload и преобразует отсутствие доступа в safe 404."""
        serializer = ProjectSubscriptionActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            project = set_workspace_project_subscription(
                project_id=project_id,
                user=request.user,
                is_subscribed=is_subscribed,
            )
        except Project.DoesNotExist as exc:
            raise NotFound("Проект не найден.") from exc
        return Response(ProjectSubscriptionStateSerializer(project).data)

    def post(self, request, project_id):
        return self.update_subscription(
            request,
            project_id,
            is_subscribed=True,
        )

    def delete(self, request, project_id):
        return self.update_subscription(
            request,
            project_id,
            is_subscribed=False,
        )
