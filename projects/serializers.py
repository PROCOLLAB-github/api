from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import serializers

from core.serializers import SkillToObjectSerializer
from core.services import get_likes_count, get_views_count, is_fan
from core.utils import get_user_online_cache_key
from files.models import UserFile
from files.serializers import UserFileSerializer
from industries.models import Industry
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
)
from partner_programs.serializers import (
    PartnerProgramFieldSerializer,
    PartnerProgramFieldValueSerializer,
)
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
    partner_program_fields = serializers.SerializerMethodField()
    partner_program_field_values = serializers.SerializerMethodField()

    def get_partner_program_fields(self, project):
        try:
            program_project = project.program_links.select_related(
                "partner_program"
            ).get()
        except PartnerProgramProject.DoesNotExist:
            return []
        fields_qs = program_project.partner_program.fields.all()
        serializer = PartnerProgramFieldSerializer(fields_qs, many=True)
        return serializer.data

    def get_partner_program_field_values(self, project):
        try:
            program_project = project.program_links.select_related(
                "partner_program"
            ).get()
        except PartnerProgramProject.DoesNotExist:
            return []
        values_qs = PartnerProgramFieldValue.objects.filter(
            program_project=program_project
        ).select_related("field")
        serializer = PartnerProgramFieldValueSerializer(values_qs, many=True)
        return serializer.data

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
            "partner_program_fields",
            "partner_program_field_values",
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


class ProjectDuplicateRequestSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    partner_program_id = serializers.IntegerField()

    def validate(self, data):
        project_id = data["project_id"]
        partner_program_id = data["partner_program_id"]
        request = self.context["request"]

        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            raise serializers.ValidationError("Проект с указанным ID не найден.")

        if project.leader != request.user:
            raise serializers.ValidationError(
                "Только лидер проекта может дублировать его в программу."
            )

        try:
            partner_program = PartnerProgram.objects.get(pk=partner_program_id)
        except PartnerProgram.DoesNotExist:
            raise serializers.ValidationError(
                "Партнёрская программа с указанным ID не найдена."
            )

        exists = PartnerProgramProject.objects.filter(
            project__name=project.name, partner_program=partner_program
        ).exists()

        if exists:
            raise serializers.ValidationError(
                f"Проект с именем '{project.name}' уже привязан к партнёрской программе '{partner_program.name}'."
            )

        return data


class PartnerProgramFieldValueUpdateSerializer(serializers.Serializer):
    field_id = serializers.PrimaryKeyRelatedField(
        queryset=PartnerProgramField.objects.all(),
        source="field",
    )
    value_text = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Укажите значение для текстового поля.",
    )

    def validate(self, attrs):
        field = attrs.get("field")
        value_text = attrs.get("value_text")

        is_required = field.is_required

        if field.field_type == "text" or field.field_type == "text":
            if is_required and (value_text is None or value_text == "textarea"):
                raise serializers.ValidationError(
                    "Поле должно содержать текстовое значение."
                )
        elif field.field_type == "checkbox":
            if is_required and value_text in (None, ""):
                raise serializers.ValidationError(
                    "Значение обязательно для поля типа 'checkbox'."
                )
            if value_text is not None:
                if isinstance(value_text, bool):
                    attrs["value_text"] = "true" if value_text else "false"
                elif isinstance(value_text, str):
                    if value_text.lower() not in ("true", "false"):
                        raise serializers.ValidationError(
                            "Для поля типа 'checkbox' ожидается 'true' или 'false'."
                        )
                    attrs["value_text"] = value_text.lower()
                else:
                    raise serializers.ValidationError(
                        "Неверный тип значения для поля 'checkbox'."
                    )
        else:
            raise serializers.ValidationError(
                f"Тип поля '{field.field_type}' не поддерживается."
            )
        return attrs
