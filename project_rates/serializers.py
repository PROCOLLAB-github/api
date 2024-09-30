from rest_framework import serializers

from core.services import get_views_count
from projects.models import Project
from .models import Criteria, ProjectScore
from .typing import CriteriasResponse, ProjectScoresResponse
from .validators import ProjectScoreValidator


class ProjectScoreCreateSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        self.criteria_to_get = kwargs.pop("criteria_to_get", None)
        super(ProjectScoreCreateSerializer, self).__init__(*args, **kwargs)

    class Meta:
        model = ProjectScore
        fields = ["criteria", "user", "project", "value"]
        validators = []

    def get_queryset(self):
        return self.Meta.model.objects.filter(
            criteria__id__in=self.criteria_to_get
        ).select_related("criteria", "project", "user")

    def validate(self, data):
        criteria = data["criteria"]
        data_to_validate = {
            "criteria_type": criteria.type,
            "value": data.get("value"),
            "criteria_min_value": criteria.min_value,
            "criteria_max_value": criteria.max_value,
        }
        ProjectScoreValidator.validate(**data_to_validate)
        return data


class CriteriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Criteria
        exclude = ["partner_program"]


class ProjectScoreSerializer(serializers.ModelSerializer):
    criteria = CriteriaSerializer()

    class Meta:
        model = ProjectScore
        fields = [
            "criteria",
            "value",
        ]

    def to_representation(self, instance):
        """For a 'flat' structure without nesting."""
        representation = super().to_representation(instance)
        criteria_data = representation.pop("criteria")
        return {**criteria_data, **representation}


class ProjectListForRateSerializer(serializers.ModelSerializer):
    views_count = serializers.SerializerMethodField()
    criterias = serializers.SerializerMethodField()
    scored = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "leader",
            "description",
            "image_address",
            "presentation_address",
            "industry",
            "region",
            "views_count",
            "scored",
            "criterias",
        ]

    def get_views_count(self, obj) -> int:
        return get_views_count(obj)

    def get_criterias(self, obj) -> CriteriasResponse | ProjectScoresResponse:
        program_id = self.context["view"].kwargs.get("program_id")
        if obj.scored:
            scores = ProjectScore.objects.filter(project=obj).select_related("criteria")
            serializer = ProjectScoreSerializer(scores, many=True)
        else:
            cirterias = Criteria.objects.filter(partner_program__id=program_id)
            serializer = CriteriaSerializer(cirterias, many=True)
        return serializer.data

    def get_scored(self, obj) -> bool:
        return bool(obj.scored)
