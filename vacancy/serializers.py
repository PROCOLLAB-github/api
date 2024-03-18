from django.contrib.auth import get_user_model
from rest_framework import serializers

from projects.models import Project
from users.serializers import UserDetailSerializer, CustomListField
from vacancy.models import Vacancy, VacancyResponse

User = get_user_model()


class RequiredSkillsSerializerMixin(serializers.Serializer):
    required_skills = CustomListField(child=serializers.CharField())


class ProjectForVacancySerializer(serializers.ModelSerializer[Project]):
    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "description",
            "image_address",
        ]


class VacancyDetailSerializer(serializers.ModelSerializer, RequiredSkillsSerializerMixin[Vacancy]):
    project = ProjectForVacancySerializer(many=False, read_only=True)

    class Meta:
        model = Vacancy
        fields = [
            "id",
            "role",
            "required_skills",
            "description",
            "project",
            "is_active",
            "datetime_created",
            "datetime_updated",
        ]
        read_only_fields = ["project"]


class VacancyListSerializer(serializers.ModelSerializer, RequiredSkillsSerializerMixin[Vacancy]):
    class Meta:
        model = Vacancy
        fields = [
            "id",
            "role",
            "required_skills",
            "description",
            "is_active",
        ]
        read_only_fields = [
            "project",
        ]


class ProjectVacancyListSerializer(
    serializers.ModelSerializer, RequiredSkillsSerializerMixin[Project]
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
        ]


class ProjectVacancyCreateListSerializer(
    serializers.ModelSerializer, RequiredSkillsSerializerMixin[Project]
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
        ]

    def create(self, validated_data):
        if validated_data["project"].draft:
            validated_data["is_active"] = False
        else:
            validated_data["is_active"] = True

        instance = super().create(validated_data)

        return instance


class VacancyResponseListSerializer(serializers.ModelSerializer[VacancyResponse]):
    is_approved = serializers.BooleanField(read_only=True)
    user = UserDetailSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = VacancyResponse
        fields = [
            "id",
            "user",
            "user_id",
            "why_me",
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


class VacancyResponseDetailSerializer(serializers.ModelSerializer[VacancyResponse]):
    user = UserDetailSerializer(many=False, read_only=True)
    vacancy = VacancyListSerializer(many=False, read_only=True)
    is_approve