from rest_framework import serializers

from rate_projects.constants import get_type
from rate_projects.models import ProjectScore
from rate_projects.validators import ProjectScoreValidate


class ProjectScoreCreateSerializer(serializers.ModelSerializer[ProjectScore]):
    class Meta:
        model = ProjectScore
        fields = [
            "criteria",
            "user",
            "project",
            "value_int",
            "value_float",
            "value_bool",
            "value_str"
        ]


