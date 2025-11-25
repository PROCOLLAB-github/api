from django.db.models import Q
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, viewsets

from kanban.models import Board
from kanban.serializers import BoardSerializer
from projects.models import Collaborator


class BoardViewSet(viewsets.ModelViewSet):
    serializer_class = BoardSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        collaborator_projects = Collaborator.objects.filter(user=user).values(
            "project_id"
        )
        return (
            Board.objects.select_related("project")
            .prefetch_related("columns")
            .filter(
                Q(project__leader_id=user.id) | Q(project_id__in=collaborator_projects)
            )
            .distinct()
        )

    def perform_destroy(self, instance):
        # TODO: в будущем реализовать проверку прав на удаление досок
        return super().perform_destroy(instance)

    @swagger_auto_schema(tags=["Kanban Boards"])
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Boards"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Boards"])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Boards"])
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Boards"])
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Boards"])
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
