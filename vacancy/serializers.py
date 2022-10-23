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

    def create(self, validated_data):
        vacancy = Vacancy(**validated_data)
        vacancy.save()

        return vacancy


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

    def create(self, validated_data):
        vacancy_request = VacancyResponse(**validated_data)
        vacancy_request.save()

        return vacancy_request
