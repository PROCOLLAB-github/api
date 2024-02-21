from rest_framework import serializers


from rate_projects.models import ProjectScore, Criteria
from rate_projects.validators import ProjectScoreValidate


class ProjectScoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectScore
        fields = ["criteria_id", "user_id", "project_id", "value"]
        readonly_field = ["criterion_field"]


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
