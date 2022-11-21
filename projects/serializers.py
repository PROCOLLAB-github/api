from rest_framework import serializers

from core.fields import CustomListField
from industries.models import Industry
from projects.models import Project, Achievement, Collaborator
from projects.validators import validate_project
from vacancy.serializers import ProjectVacancyListSerializer


class AchievementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = [
            "id",
            "title",
            "status",
        ]
        ref_name = "Projects"


class ProjectAchievementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = [
            "id",
            "title",
            "status",
            "project",
        ]


class CollaboratorSerializer(serializers.ModelSerializer):
    # specify so that there's a clear indication that it's the user's id and not collaborator's id
    user_id = serializers.IntegerField(source="user.id")
    first_name = serializers.CharField(source="user.first_name")
    last_name = serializers.CharField(source="user.last_name")
    avatar = serializers.CharField(source="user.avatar")
    key_skills = CustomListField(child=serializers.CharField(), source="user.key_skills")

    class Meta:
        model = Collaborator
        fields = [
            "user_id",
            "first_name",
            "last_name",
            "role",
            "key_skills",
            "avatar",
        ]


class ProjectCollaboratorSerializer(serializers.ModelSerializer):
    collaborators = CollaboratorSerializer(source="collaborator_set", many=True)

    class Meta:
        model = Project
        fields = ["collaborators"]


class ProjectDetailSerializer(serializers.ModelSerializer):
    achievements = AchievementListSerializer(many=True, read_only=True)
    collaborators = CollaboratorSerializer(
        source="collaborator_set", many=True, read_only=True
    )
    vacancies = ProjectVacancyListSerializer(many=True, read_only=True)
    short_description = serializers.SerializerMethodField()
    industry_id = serializers.IntegerField(required=False)

    def validate(self, data):
        super().validate(data)
        return validate_project(data)

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        instance.save()
        return instance

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
            "industry_id",
            "presentation_address",
            "image_address",
            "collaborators",
            "leader",
            "draft",
            "vacancies",
            "datetime_created",
            "datetime_updated",
        ]
        read_only_fields = ["leader"]


class ProjectListSerializer(serializers.ModelSerializer):
    collaborators = serializers.SerializerMethodField(method_name="get_collaborators")
    collaborator_count = serializers.SerializerMethodField(
        method_name="get_collaborator_count"
    )
    vacancies = ProjectVacancyListSerializer(many=True, read_only=True)

    short_description = serializers.SerializerMethodField()

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    @classmethod
    def get_collaborator_count(cls, obj):
        return len(obj.collaborator_set.all())

    def get_collaborators(self, obj):
        max_collaborator_count = 4
        return CollaboratorSerializer(
            instance=obj.collaborator_set.all()[:max_collaborator_count], many=True
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

    def validate(self, data):
        super().validate(data)
        return validate_project(data)


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
    projects = ProjectListSerializer(many=True, read_only=True)

    class Meta:
        model = Achievement
        fields = [
            "id",
            "title",
            "status",
            "projects",
        ]
        ref_name = "Projects"
