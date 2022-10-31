from rest_framework import serializers

from projects.serializers import ProjectListSerializer
from users.serializers import UserSerializer
from vacancy.models import Vacancy, VacancyResponse


class VacancyDetailSerializer(serializers.ModelSerializer):
    project = ProjectListSerializer(many=False)

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


class VacancyListSerializer(serializers.ModelSerializer):
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


class VacancyResponseListSerializer(serializers.ModelSerializer):
    class Meta:
        model = VacancyResponse
        fields = [
            "id",
            "user",
            "vacancy",
            "why_me",
            "is_approved",
            "datetime_created",
            "datetime_updated",
        ]


class VacancyResponseDetailSerializer(serializers.ModelSerializer):
    vacancy = VacancyListSerializer(many=False)
    user = UserSerializer(many=False)

    class Meta:
        model = VacancyResponse
        fields = [
            "id",
            "user",
            "vacancy",
            "why_me",
            "is_approved",
            "datetime_created",
            "datetime_updated",
        ]
