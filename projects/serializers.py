from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import serializers

from core.serializers import SkillToObjectSerializer
from core.services import get_likes_count, get_views_count, is_fan
from core.utils import get_user_online_cache_key
from files.serializers import UserFileSerializer
from industries.models import Industry
from projects.models import Achievement, Collaborator, Project, ProjectNews
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
    skills = SkillToObjectSerializer(many=True, read_only=True, source="user.skills")

    class Meta:
        model = Collaborator
        fields = [
            "user_id",
            "first_name",
            "last_name",
            "role",
            "skills",
            "avatar",
        ]


class ProjectCollaboratorSerializer(serializers.ModelSerializer):
    collaborators = CollaboratorSerializer(source="collaborator_set", many=True)

    class Meta:
        model = Project
        fields = ["collaborators"]


class ProjectDetailSerializer(serializers.ModelSerializer):
    achievements = AchievementListSerializer(many=True, read_only=True)
    cover = UserFileSerializer(required=False)
    collaborators = CollaboratorSerializer(
        source="collaborator_set", many=True, read_only=True
    )
    vacancies = ProjectVacancyListSerializer(many=True, read_only=True)
    short_description = serializers.SerializerMethodField()
    industry_id = serializers.IntegerField(required=False)
    views_count = serializers.SerializerMethodField(method_name="count_views")
    links = serializers.SerializerMethodField()
    partner_programs_tags = serializers.SerializerMethodField()
    track = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    direction = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    actuality = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    goal = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    problem = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    @classmethod
    def get_partner_programs_tags(cls, project):
        profiles_qs = project.partner_program_profiles.select_related(
            "partner_program"
        ).only("partner_program__tag")
        return [profile.partner_program.tag for profile in profiles_qs]

    @classmethod
    def get_links(cls, project):
        return [link.link for link in project.links.all()]

    def validate(self, data):
        super().validate(data)
        return validate_project(data)

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    def count_views(self, project):
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
            "is_company",
            "vacancies",
            "datetime_created",
            "datetime_updated",
            "views_count",
            "cover",
            "cover_image_address",
            "partner_programs_tags",
            "track",
            "direction",
            "actuality",
            "goal",
            "problem",
        ]
        read_only_fields = [
            "leader",
            "views_count",
            "datetime_created",
            "datetime_updated",
            "is_company",
        ]


class ProjectListSerializer(serializers.ModelSerializer):
    views_count = serializers.SerializerMethodField(method_name="count_views")
    short_description = serializers.SerializerMethodField()

    @classmethod
    def count_views(cls, project):
        return get_views_count(project)

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "leader",
            "short_description",
            "image_address",
            "industry",
            "views_count",
            "is_company",
        ]

        read_only_fields = ["leader", "views_count", "is_company"]

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
        # fixme: move this method to helpers somewhere
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


class ProjectSubscribersListSerializer(serializers.ModelSerializer):
    is_online = serializers.SerializerMethodField()

    def get_is_online(self, user: User) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated and request.user.id == user.id:
            return True

        cache_key = get_user_online_cache_key(user)
        is_online = cache.get(cache_key, False)
        return is_online

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "avatar",
            "is_online",
        ]
