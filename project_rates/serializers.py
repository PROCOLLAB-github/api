from rest_framework import serializers

from core.services import get_views_count
from .models import Criteria, ProjectScore
from projects.models import Project
from .validators import ProjectScoreValidate


class ProjectScoreCreateSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        self.criteria_to_get = kwargs.pop("criteria_to_get", None)
        super(ProjectScoreCreateSerializer, self).__init__(*args, **kwargs)

    class Meta:
        model = ProjectScore
        fields = ("criteria", "user", "project", "value")
        validators = []

    def get_queryset(self):
        return self.Meta.model.objects.filter(
            criteria__id__in=self.criteria_to_get
        ).select_related("criteria", "project", "user")

    def validate(self, data):
        criteria = data["criteria"]
        ProjectScoreValidate(
            criteria_type=criteria.type,
            value=data.get("value"),
            criteria_min_value=criteria.min_value,
            criteria_max_value=criteria.max_value,
        )
        return data


class CriteriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Criteria
        exclude = ["partner_program"]


class ProjectScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["criteria_id", "project_id", "value"]


class ProjectScoreGetSerializer(serializers.ModelSerializer):
    views_count = serializers.SerializerMethodField(method_name="count_views")
    criterias = serializers.SerializerMethodField()

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
            "criterias",
        ]

    def get_criterias(self, obj):
        criterias = []
        for criteria in self.context["data_criterias"]:
            copied_criteria = criteria.copy()
            for score in self.context["data_scores"]:
                if (
                    criteria["id"] == score["criteria_id"]
                    and obj.id == score["project_id"]
                ):
                    copied_criteria["value"] = score["value"]

            criterias.append(copied_criteria)
        return criterias

    @classmethod
    def count_views(cls, project):
        return get_views_count(project)


class ScoredProjectsSerializer(ProjectScoreGetSerializer):
    scores_count = serializers.IntegerField()

    class Meta(ProjectScoreGetSerializer.Meta):
        fields = ProjectScoreGetSerializer.Meta.fields + ["scores_count"]


def serialize_data_func(criteria_to_get: list, data: dict):
    criteria = Criteria.objects.in_bulk(criteria_to_get)

    for criterion in data:
        needed_criteria = criteria.get(int(criterion["criterion_id"]))

        ProjectScoreValidate(
            criteria_type=needed_criteria.type,
            value=criterion["value"],
            criteria_min_value=needed_criteria.min_value,
            criteria_max_value=needed_criteria.max_value,
        )
        criterion["criteria_id"] = criterion.pop("criterion_id")
