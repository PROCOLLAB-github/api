from rest_framework import serializers

from industries.models import Industry
from projects.models import Project, Achievement, Collaborator
from users.models import CustomUser
from vacancy.serializers import ProjectVacancyListSerializer


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
    first_name = serializers.CharField(source="user.first_name")
    last_name = serializers.CharField(source="user.last_name")
    avatar = serializers.CharField(source="user.avatar")
    member_key_skills = serializers.SerializerMethodField()

    @classmethod
    def get_member_key_skills(cls, collaborator):
        return collaborator.user.get_member_key_skills()

    class Meta:
        model = Collaborator
        fields = [
            "id",
            "first_name",
            "last_name",
            "role",
            "member_key_skills",
            "avatar",
        ]


class ProjectDetailSerializer(serializers.ModelSerializer):
    achievements = AchievementListSerializer(many=True, read_only=True)
    collaborators = ProjectCollaboratorSerializer(
        source="collaborator_set", many=True, read_only=True
    )
    vacancies = ProjectVacancyListSerializer(many=True, read_only=True)

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
    collaborators = serializers.SerializerMethodField(method_name="get_collaborators")
    collaborator_count = serializers.SerializerMethodField(
        method_name="get_collaborator_count"
    )
    vacancies = ProjectVacancyListSerializer(many=True, read_only=True)

    @classmethod
    def get_collaborator_count(cls, obj):
        return len(obj.collaborator_set.all())

    @classmethod
    def get_collaborators(cls, obj):
        return ProjectCollaboratorSerializer(
            instance=obj.collaborator_set.all()[:4], many=True
        ).data

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
            "collaborator_count",
            "collaborators",
            "vacancies",
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
