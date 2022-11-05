from rest_framework import serializers

from industries.models import Industry
from projects.models import Project, Achievement, Collaborator
from users.models import CustomUser


class AchievementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = [
            "id",
            "title",
            "status",
        ]


class ProjectAchievementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = [
            "id",
            "title",
            "status",
            "project",
        ]


class ProjectCollaboratorSerializer(serializers.ModelSerializer):
    # id = serializers.IntegerField(source="user.id")
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    key_skills = serializers.SerializerMethodField()

    class Meta:
        model = Collaborator
        fields = [
            "id",
            "first_name",
            "last_name",
            "avatar",
            "key_skills",
        ]

    def get_first_name(self, obj):
        return obj.first_name

    def get_last_name(self, obj):
        return obj.last_name

    def get_avatar(self, obj):
        return obj.avatar

    def get_key_skills(self, obj):
        return obj.get_member_key_skills()

    def get_queryset(self):
        return Collaborator.objects.all()


class ProjectDetailSerializer(serializers.ModelSerializer):
    achievements = AchievementListSerializer(many=True, read_only=True)
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


class ProjectListSerializer(serializers.ModelSerializer):
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
        read_only_fields = [
            "leader",
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


class ProjectIndustrySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField()
    name = serializers.CharField(read_only=True)

    class Meta:
        model = Industry
        fields = [
            "id",
            "name",
        ]


class ProjectCollaboratorsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Collaborator
        fields = [
            "user",
            "project",
            "role",
            "datetime_created",
        ]


class AchievementDetailSerializer(serializers.ModelSerializer):
    project = ProjectListSerializer(many=False, read_only=True)

    class Meta:
        model = Achievement
        fields = [
            "id",
            "title",
            "status",
            "project",
        ]
