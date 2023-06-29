from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.fields import CustomListField
from core.services import get_views_count, get_likes_count, is_fan
from industries.models import Industry
from projects.models import Project, Achievement, Collaborator, ProjectNews
from projects.validators import validate_project
from vacancy.serializers import ProjectVacancyListSerializer

User = get_user_model()


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
    likes_count = serializers.SerializerMethodField(method_name="count_likes")
    views_count = serializers.SerializerMethodField(method_name="count_views")
    links = serializers.SerializerMethodField()

    @classmethod
    def get_links(cls, project):
        return [link.link for link in project.links.all()]

    def validate(self, data):
        super().validate(data)
        return validate_project(data)

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    def count_likes(self, project):
        # FIXME
        # TODO: add caching here at least every 5 minutes, otherwise this will be heavy load
        return get_likes_count(project)

    def count_views(self, project):
        # FIXME
        # TODO: add caching here at least every 5 minutes, otherwise this will be heavy load
        return get_views_count(project)

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
            "links",
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
            "views_count",
            "likes_count",
        ]
        read_only_fields = [
            "leader",
            "views_count",
            "datetime_created",
            "datetime_updated",
        ]


class ProjectListSerializer(serializers.ModelSerializer):
    collaborators = serializers.SerializerMethodField(method_name="get_collaborators")
    likes_count = serializers.SerializerMethodField(method_name="count_likes")
    collaborator_count = serializers.SerializerMethodField(
        method_name="get_collaborator_count"
    )
    vacancies = ProjectVacancyListSerializer(many=True, read_only=True)
    views_count = serializers.SerializerMethodField(method_name="count_views")

    def count_views(self, project):
        # FIXME
        # TODO: add caching here at least every 5 minutes, otherwise will be heavy load
        return get_views_count(project)

    short_description = serializers.SerializerMethodField()

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    @classmethod
    def get_collaborator_count(cls, obj):
        return len(obj.collaborator_set.all())

    def count_likes(self, obj):
        return get_likes_count(obj)

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
            "likes_count",
            "views_count",
        ]

        read_only_fields = ["leader", "views_count"]

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


class ProjectNewsListSerializer(serializers.ModelSerializer):
    views_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()
    project_image_address = serializers.SerializerMethodField()
    is_user_liked = serializers.SerializerMethodField()

    def get_project_name(self, obj):
        return obj.project.name

    def get_project_image_address(self, obj):
        return obj.project.image_address

    def get_views_count(self, obj):
        return get_views_count(obj)

    def get_likes_count(self, obj):
        return get_likes_count(obj)

    def get_is_user_liked(self, obj):
        user = self.context.get("user")
        if user:
            return is_fan(obj, user)
        return False

    class Meta:
        model = ProjectNews
        fields = [
            "id",
            "project_name",
            "project_image_address",
            "text",
            "datetime_created",
            "views_count",
            "likes_count",
            "is_user_liked",
            "files",
        ]


class ProjectNewsDetailSerializer(serializers.ModelSerializer):
    views_count = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()
    project_image_address = serializers.SerializerMethodField()
    is_user_liked = serializers.SerializerMethodField()

    def get_project_name(self, obj):
        return obj.project.name

    def get_project_image_address(self, obj):
        return obj.project.image_address

    def get_views_count(self, obj):
        return get_views_count(obj)

    def get_likes_count(self, obj):
        return get_likes_count(obj)

    def get_is_user_liked(self, obj):
        user = self.context.get("user")
        if user:
            return is_fan(obj, user)
        return False

    class Meta:
        model = ProjectNews
        fields = [
            "id",
            "project_name",
            "project_image_address",
            "text",
            "datetime_created",
            "datetime_updated",
            "views_count",
            "likes_count",
            "is_user_liked",
            "files",
        ]
