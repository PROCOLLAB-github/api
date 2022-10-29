from rest_framework import serializers

from projects.models import Project, Achievement
from users.models import CustomUser


class ProjectDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "description",
            "short_description",
            "achievements",
            "region",
            "step",
            "industry",
            "presentation_address",
            "image_address",
            "collaborators",
            "leader",
            "draft",
            "datetime_created",
            "datetime_updated",
        ]


class ProjectListSerializer(serializers.ModelSerializer):
    industry = serializers.SlugRelatedField("name", read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "leader",
            "description",
            "short_description",
            "step",
            "industry",
            "image_address",
            "draft",
            "datetime_created",
        ]


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = [
            "id",
            "title",
            "status",
            "project",
        ]


class ProjectCollaboratorsSerializer(serializers.Serializer):
    collaborators = serializers.PrimaryKeyRelatedField(
        queryset=CustomUser.objects.all(), many=True, read_only=False
    )
