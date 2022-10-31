from rest_framework import serializers

from industries.models import Industry
from projects.models import Project, Achievement
from users.models import CustomUser


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = [
            "id",
            "title",
            "status",
        ]

    def get_queryset(self):
        return Achievement.objects.all()


class ProjectCollaboratorSerializer(serializers.ModelSerializer):
    key_skills = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "first_name",
            "last_name",
            "avatar",
            "key_skills",
        ]

    def get_key_skills(self, obj):
        return obj.get_member_key_skills()

    def get_queryset(self):
        return CustomUser.objects.all()


class ProjectDetailSerializer(serializers.ModelSerializer):
    achievements = AchievementSerializer(many=True, read_only=True)
    collaborators = ProjectCollaboratorSerializer(many=True, read_only=True)

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


class ProjectIndustrySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField()
    name = serializers.CharField(read_only=True)

    class Meta:
        model = Industry
        fields = [
            "id",
            "name",
        ]

    def get_queryset(self):
        return Industry.objects.all()


class ProjectListSerializer(serializers.ModelSerializer):
    # industry = ProjectIndustrySerializer(read_only=False, required=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "leader",
            "description",
            "short_description",
            "step",
            "image_address",
            "draft",
            "industry",
            "datetime_created",
        ]

    def is_valid(self, *, raise_exception=False):
        return super().is_valid(raise_exception=raise_exception)

    def create(self, validated_data):
        industry = Industry.objects.get(id=validated_data.pop("industry"))
        leader = CustomUser.objects.get(id=validated_data.pop("leader"))
        project = Project.objects.create(
            **validated_data,
            industry=industry,
            leader=leader,
        )
        return project


class ProjectCollaboratorsSerializer(serializers.Serializer):
    collaborators = serializers.PrimaryKeyRelatedField(
        queryset=CustomUser.objects.all(), many=True, read_only=False
    )
