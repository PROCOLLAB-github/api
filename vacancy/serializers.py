from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from core.models import Skill, SkillToObject
from core.serializers import SkillToObjectSerializer
from files.models import UserFile
from files.serializers import UserFileSerializer
from projects.models import Project
from users.serializers import UserDetailSerializer
from vacancy.models import Vacancy, VacancyResponse

User = get_user_model()


class RequiredSkillsSerializerMixin(serializers.Serializer):
    required_skills = SkillToObjectSerializer(many=True, read_only=True)


class RequiredSkillsWriteSerializerMixin(RequiredSkillsSerializerMixin):
    required_skills_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )


class AbstractVacancyReadOnlyFields(serializers.Serializer):
    """Abstract read-only fields for Vacancy."""
    datetime_closed = serializers.DateTimeField(read_only=True)
    response_count = serializers.SerializerMethodField(read_only=True)

    def get_response_count(self, obj):
        """Returns count non status responses."""
        return obj.vacancy_requests.filter(is_approved=None).count()


class ProjectForVacancySerializer(serializers.ModelSerializer[Project]):
    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "description",
            "image_address",
        ]


class VacancyDetailSerializer(
    serializers.ModelSerializer,
    AbstractVacancyReadOnlyFields,
    RequiredSkillsWriteSerializerMixin[Vacancy],
):
    project = ProjectForVacancySerializer(many=False, read_only=True)

    class Meta:
        model = Vacancy
        fields = [
            "id",
            "role",
            "required_skills",
            "required_skills_ids",
            "description",
            "project",
            "is_active",
            "datetime_created",
            "datetime_updated",
            "datetime_closed",
            "response_count",
        ]
        read_only_fields = ["project"]


class VacancyListSerializer(
    serializers.ModelSerializer,
    RequiredSkillsSerializerMixin[Vacancy],
    AbstractVacancyReadOnlyFields,
):
    class Meta:
        model = Vacancy
        fields = [
            "id",
            "role",
            "required_skills",
            "description",
            "is_active",
            "datetime_closed",
            "response_count",
        ]
        read_only_fields = [
            "project",
        ]


class ProjectVacancyListSerializer(
    serializers.ModelSerializer,
    AbstractVacancyReadOnlyFields,
    RequiredSkillsSerializerMixin[Vacancy],
):
    class Meta:
        model = Vacancy
        fields = [
            "id",
            "role",
            "required_skills",
            "description",
            "project",
            "is_active",
            "datetime_closed",
            "response_count",
        ]


class ProjectVacancyCreateListSerializer(
    serializers.ModelSerializer,
    AbstractVacancyReadOnlyFields,
    RequiredSkillsWriteSerializerMixin[Vacancy],
):
    def create(self, validated_data):
        project = validated_data["project"]
        if project.leader != self.context["request"].user:
            raise serializers.ValidationError("You are not the leader of the project")

        required_skills_ids = validated_data.pop("required_skills_ids")

        if validated_data["project"].draft:
            validated_data["is_active"] = False
        else:
            validated_data["is_active"] = True

        vacancy = Vacancy.objects.create(**validated_data)

        for skill_id in required_skills_ids:
            try:
                skill = Skill.objects.get(id=skill_id)
            except Skill.DoesNotExist:
                raise serializers.ValidationError(
                    f"Skill with id {skill_id} does not exist"
                )

            SkillToObject.objects.create(
                skill=skill,
                content_type=ContentType.objects.get_for_model(Vacancy),
                object_id=vacancy.id,
            )

        return vacancy

    class Meta:
        model = Vacancy
        fields = [
            "id",
            "role",
            "required_skills",
            "required_skills_ids",
            "description",
            "project",
            "is_active",
            "datetime_closed",
            "response_count",
        ]


class VacancyResponseListSerializer(serializers.ModelSerializer[VacancyResponse]):
    is_approved = serializers.BooleanField(read_only=True)
    user = UserDetailSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    accompanying_file = serializers.SlugRelatedField(
        slug_field="link",
        queryset=UserFile.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = VacancyResponse
        fields = [
            "id",
            "user",
            "user_id",
            "why_me",
            "accompanying_file",
            "is_approved",
            "vacancy",
        ]
        extra_kwargs = {
            "user_id": {"write_only": True},
        }

    def validate(self, attrs):
        vacancy = attrs["vacancy"]
        user = self.validate_user_exists(attrs["user_id"])

        if VacancyResponse.objects.filter(vacancy=vacancy, user=user).exists():
            raise serializers.ValidationError("Vacancy response already exists")
        return attrs

    def validate_user_exists(self, value):
        try:
            user = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User does not exist")
        return user

    def create(self, validated_data):
        user_id = validated_data.pop("user_id")
        user = User.objects.get(pk=user_id)
        vacancy_response = VacancyResponse.objects.create(user=user, **validated_data)
        return vacancy_response


class VacancyResponseFullFileInfoListSerializer(VacancyResponseListSerializer):
    """Returns full file info."""
    accompanying_file = UserFileSerializer(read_only=True)


class VacancyResponseDetailSerializer(serializers.ModelSerializer[VacancyResponse]):
    user = UserDetailSerializer(many=False, read_only=True)
    vacancy = VacancyListSerializer(many=False, read_only=True)
    is_approved = serializers.BooleanField(read_only=True)
    accompanying_file = serializers.SlugRelatedField(
        slug_field="link",
        queryset=UserFile.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = VacancyResponse
        fields = [
            "id",
            "user",
            "vacancy",
            "why_me",
            "accompanying_file",
            "is_approved",
            "datetime_created",
            "datetime_updated",
        ]


class VacancyResponseAcceptSerializer(VacancyResponseDetailSerializer[VacancyResponse]):
    is_approved = serializers.BooleanField(required=True, read_only=False)
