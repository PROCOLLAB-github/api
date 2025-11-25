from django.db import transaction
from rest_framework import serializers

from kanban.models import Board, BoardColumn
from projects.models import Collaborator, Project


class BoardSerializer(serializers.ModelSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())

    class Meta:
        model = Board
        fields = (
            "id",
            "project",
            "name",
            "color",
            "icon",
            "description",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_project(self, project: Project):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Требуется аутентификация")

        if project.leader_id == user.id:
            return project

        is_member = Collaborator.objects.filter(
            project_id=project.id,
            user_id=user.id,
        ).exists()
        if not is_member:
            raise serializers.ValidationError("Пользователь не является участником проекта")
        return project

    def create(self, validated_data):
        with transaction.atomic():
            board = super().create(validated_data)
            if not board.columns.exists():
                BoardColumn.objects.create(board=board, name="Бэклог", order=1)
        return board


class BoardColumnSerializer(serializers.ModelSerializer):
    board = serializers.PrimaryKeyRelatedField(queryset=Board.objects.all())
    tasks_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = BoardColumn
        fields = (
            "id",
            "board",
            "name",
            "order",
            "tasks_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tasks_count", "created_at", "updated_at")

    def validate_board(self, board: Board):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Требуется аутентификация")

        if board.project.leader_id == user.id:
            return board

        is_member = Collaborator.objects.filter(
            project_id=board.project_id,
            user_id=user.id,
        ).exists()
        if not is_member:
            raise serializers.ValidationError(
                "Пользователь не является участником проекта"
            )
        return board
