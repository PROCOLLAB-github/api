from django.forms.models import model_to_dict

from .validators import find_filled_field
from rest_framework import serializers
from .models import Criteria, ProjectScore
from projects.models import Project


class ProjectScoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = [
            "criteria",
            "user",
            "project",
            "value_int",
            "value_float",
            "value_bool",
            "value_str",
            "comment",
        ]


class CriteriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Criteria
        exclude = ["partner_program"]


class ProjectScoreSerializer(serializers.ModelSerializer):
    filled_value = serializers.SerializerMethodField()

    class Meta:
        model = ProjectScore
        fields = ["criteria_id", "project_id", "filled_value", "comment"]

    def get_filled_value(self, obj):
        return find_filled_field(model_to_dict(obj))[0]


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
                    copied_criteria["filled_value"] = score["filled_value"]
                    copied_criteria["comment"] = score["comment"]

            criterias.append(copied_criteria)
        return criterias
