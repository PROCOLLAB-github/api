from rest_framework import serializers
from .models import Criteria, ProjectScore
from projects.models import Project


class ProjectScoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["criteria", "user", "project", "value", "comment"]


class CriteriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Criteria
        exclude = ["partner_program"]


class ProjectScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["criteria_id", "project_id", "value", "comment"]


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
            copied_criteria["comment"] = None
            for score in self.context["data_scores"]:
                if (
                    criteria["id"] == score["criteria_id"]
                    and obj.id == score["project_id"]
                ):
                    copied_criteria["filled_value"] = score["value"]
                    copied_criteria["comment"] = score["comment"]

            criterias.append(copied_criteria)
        return criterias
