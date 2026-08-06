from datetime import date

from rest_framework import serializers

from projects.models import Achievement, Collaborator, ProjectGoal


class ProjectWorkspaceGoalSerializer(serializers.ModelSerializer):
    """Читает и изменяет цель только в контексте проекта из URL."""

    class Meta:
        model = ProjectGoal
        fields = ("id", "title", "completion_date", "responsible")
        read_only_fields = ("id",)

    def validate_title(self, value):
        normalized_title = value.strip()
        if not normalized_title:
            raise serializers.ValidationError("Укажите название цели.")
        return normalized_title

    def validate(self, attrs):
        project = self.context["project"]
        responsible = attrs.get(
            "responsible",
            getattr(self.instance, "responsible", None),
        )
        if responsible is None:
            return attrs

        is_project_member = (
            responsible.pk == project.leader_id
            or Collaborator.objects.filter(
                project_id=project.pk,
                user_id=responsible.pk,
            ).exists()
        )
        if not is_project_member:
            raise serializers.ValidationError(
                {
                    "responsible": (
                        "Ответственным может быть только руководитель или участник "
                        "этого проекта."
                    )
                }
            )
        return attrs


class ProjectWorkspaceAchievementSerializer(serializers.ModelSerializer):
    """Предоставляет год достижения поверх legacy-поля Achievement.status."""

    year = serializers.IntegerField(
        source="status",
        min_value=2000,
        max_value=date.today().year,
        error_messages={
            "invalid": "Укажите год целым числом.",
            "min_value": "Год не может быть раньше 2000.",
            "max_value": "Год не может быть позже текущего года.",
        },
    )

    class Meta:
        model = Achievement
        fields = ("id", "title", "year")
        read_only_fields = ("id",)

    def validate_title(self, value):
        normalized_title = value.strip()
        if not normalized_title:
            raise serializers.ValidationError("Укажите название достижения.")
        return normalized_title

    def create(self, validated_data):
        validated_data["status"] = str(validated_data["status"])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "status" in validated_data:
            validated_data["status"] = str(validated_data["status"])
        return super().update(instance, validated_data)
