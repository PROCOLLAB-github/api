from rest_framework import serializers

from vacancy.models import Vacancy, VacancyResponse


class VacancySerializer(serializers.ModelSerializer):
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


class VacancyResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = VacancyResponse
        fields = [
            "id",
            "user",
            "vacancy",
            "is_approve",
            "datetime_created",
            "datetime_updated",
        ]
