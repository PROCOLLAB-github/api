from rest_framework import serializers

from rate_projects.models import ProjectScore


class ProjectScoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["criteria_id", "user_id", "project_id", "value"]
