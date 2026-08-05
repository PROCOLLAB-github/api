from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, mixins
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from projects.models import Achievement, Project, ProjectGoal
from projects.workspace_content_serializers import (
    ProjectWorkspaceAchievementSerializer,
    ProjectWorkspaceGoalSerializer,
)
from projects.workspace_selectors import filter_workspace_visible_projects


class ProjectWorkspaceNestedObjectMixin:
    """Применяет единые workspace-права к вложенным объектам проекта."""

    permission_classes = (IsAuthenticated,)
    project_context_key = "project"

    def get_project(self):
        if not hasattr(self, "_workspace_project"):
            projects = Project.objects.only(
                "id",
                "leader_id",
                "draft",
                "is_public",
            )
            projects = filter_workspace_visible_projects(
                projects,
                user=self.request.user,
            )
            self._workspace_project = get_object_or_404(
                projects,
                pk=self.kwargs["project_id"],
            )
        return self._workspace_project

    def check_workspace_write_access(self):
        project = self.get_project()
        user = self.request.user
        if not (user.is_staff or user.is_superuser or project.leader_id == user.pk):
            raise PermissionDenied("Редактировать проект может только руководитель.")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context[self.project_context_key] = self.get_project()
        return context


class ProjectWorkspaceGoalListView(
    ProjectWorkspaceNestedObjectMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    generics.GenericAPIView,
):
    """Возвращает цели проекта и создает цель для руководителя или staff."""

    serializer_class = ProjectWorkspaceGoalSerializer

    def get_queryset(self):
        return (
            ProjectGoal.objects.filter(project=self.get_project())
            .select_related("responsible")
            .order_by("id")
        )

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        self.check_workspace_write_access()
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(project=self.get_project())


class ProjectWorkspaceGoalDetailView(
    ProjectWorkspaceNestedObjectMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    generics.GenericAPIView,
):
    """Изменяет или удаляет цель, принадлежащую проекту из URL."""

    serializer_class = ProjectWorkspaceGoalSerializer

    def get_queryset(self):
        return ProjectGoal.objects.filter(project=self.get_project()).select_related(
            "responsible"
        )

    def get_object(self):
        return get_object_or_404(
            self.get_queryset(),
            pk=self.kwargs["goal_id"],
        )

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        self.check_workspace_write_access()
        return self.partial_update(request, *args, **kwargs)

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        self.check_workspace_write_access()
        return self.destroy(request, *args, **kwargs)


class ProjectWorkspaceAchievementListView(
    ProjectWorkspaceNestedObjectMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    generics.GenericAPIView,
):
    """Возвращает достижения и создает их внутри текущего проекта."""

    serializer_class = ProjectWorkspaceAchievementSerializer

    def get_queryset(self):
        return Achievement.objects.filter(project=self.get_project()).order_by("id")

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        self.check_workspace_write_access()
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(project=self.get_project())


class ProjectWorkspaceAchievementDetailView(
    ProjectWorkspaceNestedObjectMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    generics.GenericAPIView,
):
    """Изменяет или удаляет достижение только в рамках проекта из URL."""

    serializer_class = ProjectWorkspaceAchievementSerializer

    def get_queryset(self):
        return Achievement.objects.filter(project=self.get_project())

    def get_object(self):
        return get_object_or_404(
            self.get_queryset(),
            pk=self.kwargs["achievement_id"],
        )

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        self.check_workspace_write_access()
        return self.partial_update(request, *args, **kwargs)

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        self.check_workspace_write_access()
        return self.destroy(request, *args, **kwargs)
