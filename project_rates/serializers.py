from rest_framework import serializers
from .models import Criteria, ProjectScore
from projects.models import Project
from .validators import ProjectScoreValidate


class ProjectScoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["criteria", "user", "project", "value"]


class CriteriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Criteria
        exclude = ["partner_program"]


class ProjectScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["criteria_id", "project_id", "value"]


class ProjectScoreGetSerializer(serializers.ModelSerializer):
    criterias = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "leader",
            "description",
            "image_address",
            "industry",
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
