from rest_framework import serializers


from rate_projects.models import ProjectScore
from .validators import find_filled_field


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


from rest_framework import serializers
from .models import Criteria, ProjectScore
from projects.models import Project


class CriteriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Criteria
        exclude = ['partner_program']


from django.forms.models import model_to_dict


class ProjectScoreSerializer(serializers.ModelSerializer):
    filled_value = serializers.SerializerMethodField()

    class Meta:
        model = ProjectScore
        fields = ['criteria_id', 'project_id', 'filled_value']

    def get_filled_value(self, obj):
        filled_values = [{'project_id': score.project_id, 'criteria_id': score.criteria_id, 'filled_value': find_filled_field(model_to_dict(score))[0]}
                         for score in obj]
        return filled_values


class ProjectSerializer(serializers.ModelSerializer):
    criterias = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'leader', 'description', 'image_address', 'industry', 'criterias']

    def get_criterias(self, obj):
        criterias = []
        for criteria in self.context['data_criterias']:
            copied_criteria = criteria.copy()  # Создать полную копию критерия
            for score in self.context['data_scores'][0]['filled_value']:
                if criteria['id'] == score['criteria_id'] and obj.id == score['project_id']:
                    copied_criteria['filled_value'] = score['filled_value']
            criterias.append(copied_criteria)
        return criterias
