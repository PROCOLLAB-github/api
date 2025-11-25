from django.db.models import Q, Max
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from kanban.models import Board, BoardColumn
from kanban.serializers import BoardSerializer, BoardColumnSerializer
from projects.models import Collaborator


class BoardViewSet(viewsets.ModelViewSet):
    serializer_class = BoardSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Board.objects.none()
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

    @swagger_auto_schema(tags=["Kanban Boards"])
    @action(detail=True, methods=["get"], url_path="columns")
    def columns(self, request, pk=None):
        board = self.get_object()
        columns = board.columns.order_by("order", "id")
        serializer = BoardColumnSerializer(columns, many=True)
        return Response(serializer.data)


class BoardColumnViewSet(viewsets.ModelViewSet):
    serializer_class = BoardColumnSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return BoardColumn.objects.none()
        collaborator_projects = Collaborator.objects.filter(user=user).values(
            "project_id"
        )
        return (
            BoardColumn.objects.select_related("board", "board__project")
            .filter(
                Q(board__project__leader_id=user.id)
                | Q(board__project_id__in=collaborator_projects)
            )
            .distinct()
        )

    @swagger_auto_schema(tags=["Kanban Columns"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Columns"])
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Columns"])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Columns"])
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Columns"])
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(tags=["Kanban Columns"])
    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except Exception as exc:
            from django.core.exceptions import ValidationError

            if isinstance(exc, ValidationError):
                return Response(exc.messages, status=status.HTTP_400_BAD_REQUEST)
            raise

    def perform_create(self, serializer):
        board = serializer.validated_data.get("board")
        if not board:
            raise ValidationError("Укажите board")

        user = self.request.user
        collaborator_projects = set(
            Collaborator.objects.filter(user=user).values_list("project_id", flat=True)
        )
        if not (
            board.project.leader_id == user.id
            or board.project_id in collaborator_projects
        ):
            raise ValidationError("Пользователь не является участником проекта")

        next_order = (
            BoardColumn.objects.filter(board=board).aggregate(Max("order"))["order__max"]
            or 0
        )
        serializer.save(board=board, order=next_order + 1)

    @swagger_auto_schema(
        methods=["post"],
        tags=["Kanban Columns"],
        operation_summary="Переместить колонку",
        operation_description="Изменяет порядок колонки внутри доски.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={"new_order": openapi.Schema(type=openapi.TYPE_INTEGER)},
            required=["new_order"],
        ),
    )
    @action(detail=True, methods=["post"], url_path="move")
    def move(self, request, pk=None):
        from django.db import transaction
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        from kanban.models import BoardColumn

        try:
            new_order = int(request.data.get("new_order"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "new_order должен быть числом"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        column = (
            BoardColumn.objects.select_related("board", "board__project")
            .select_for_update()
            .get(pk=pk)
        )

        with transaction.atomic():
            columns = list(
                BoardColumn.objects.filter(board=column.board)
                .select_for_update()
                .order_by("order", "id")
            )
            columns = [c for c in columns if c.id != column.id]
            insert_index = max(0, min(new_order - 1, len(columns)))
            columns.insert(insert_index, column)

            # Шаг 1: временно сдвигаем порядки, чтобы не ловить UNIQUE при массовом обновлении
            for idx, col in enumerate(columns, start=1):
                col.order = idx + 1000
            BoardColumn.objects.bulk_update(columns, ["order"])

            # Шаг 2: выставляем финальные порядки
            for idx, col in enumerate(columns, start=1):
                col.order = idx

            BoardColumn.objects.bulk_update(columns, ["order"])

        channel_layer = get_channel_layer()
        payload = {
            "action": "column.reordered",
            "board_id": column.board_id,
            "project_id": column.board.project_id,
            "columns": [{"id": c.id, "order": c.order, "name": c.name} for c in columns],
        }
        async_to_sync(channel_layer.group_send)(
            f"kanban_{column.board.project_id}",
            {"type": "kanban.event", "payload": payload},
        )

        serializer = self.get_serializer(columns, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
