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
    expert_id = serializers.IntegerField(source="user_id", read_only=True)

    class Meta:
        model = ProjectScore
        fields = [
            "criteria",
            "expert_id",
            "value",
        ]

    def to_representation(self, instance):
        """For a 'flat' structure without nesting."""
        representation = super().to_representation(instance)
        criteria_data = representation.pop("criteria")
        return {**criteria_data, **representation}


class ProjectListForRateSerializer(serializers.ModelSerializer):
    managed_evaluation = serializers.SerializerMethodField()
    criteria_revision = serializers.SerializerMethodField()
    views_count = serializers.SerializerMethodField()
    criterias = serializers.SerializerMethodField()
    scored = serializers.SerializerMethodField()
    rated_experts = serializers.SerializerMethodField()
    rated_count = serializers.SerializerMethodField()
    max_rates = serializers.SerializerMethodField()

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
            "rated_experts",
            "rated_count",
            "max_rates",
            "criterias",
            "criteria_revision",
            "managed_evaluation",
        ]

    def get_criteria_revision(self, obj):
        return self.context.get("criteria_revision")

    def get_managed_evaluation(self, obj):
        return bool(self.context.get("managed_evaluation"))

    def get_views_count(self, obj) -> int:
        return get_views_count(obj)

    def _get_program_scores(self, obj):
        if hasattr(obj, "_program_scores"):
            return obj._program_scores
        program_id = self.context["view"].kwargs.get("program_id")
        return ProjectScore.objects.filter(
            project=obj, criteria__partner_program_id=program_id
        ).select_related("criteria", "user")

    def _get_user_scores(self, obj):
        scores = self._get_program_scores(obj)
        request = self.context.get("request")
        if request and getattr(request.user, "is_authenticated", False):
            return [score for score in scores if score.user_id == request.user.id]
        return []

    def get_criterias(self, obj) -> CriteriasResponse | ProjectScoresResponse:
        user_scores = self._get_user_scores(obj)
        if self.context.get("managed_evaluation"):
            program_id = self.context["view"].kwargs.get("program_id")
            scores = {score.criteria_id: score for score in user_scores}
            return [
                {
                    **CriteriaSerializer(c).data,
                    **({"value": scores[c.pk].value} if c.pk in scores else {}),
                }
                for c in Criteria.objects.filter(partner_program_id=program_id).order_by(
                    "pk"
                )
            ]
        if user_scores:
            serializer = ProjectScoreSerializer(user_scores, many=True)
            return serializer.data
        program_id = self.context["view"].kwargs.get("program_id")
        criterias = Criteria.objects.filter(partner_program__id=program_id)
        serializer = CriteriaSerializer(criterias, many=True)
        return serializer.data

    def get_scored(self, obj) -> bool:
        if hasattr(obj, "_own_completed"):
            return obj._own_completed
        user_scores = self._get_user_scores(obj)
        if self.context.get("managed_evaluation"):
            program_id = self.context["view"].kwargs.get("program_id")
            required = set(
                Criteria.objects.filter(partner_program_id=program_id).values_list(
                    "pk", flat=True
                )
            )
            return bool(required) and required.issubset(
                {score.criteria_id for score in user_scores}
            )
        return bool(user_scores)

    def get_rated_experts(self, obj) -> list[int]:
        program_scores = self._get_program_scores(obj)
        if self.context.get("managed_evaluation"):
            from collections import defaultdict

            required = set(
                Criteria.objects.filter(
                    partner_program_id=self.context["view"].kwargs["program_id"]
                ).values_list("pk", flat=True)
            )
            scored = defaultdict(set)
            for score in program_scores:
                scored[score.user_id].add(score.criteria_id)
            return [
                user_id
                for user_id, ids in scored.items()
                if required and required.issubset(ids)
            ]
        return list({score.user_id for score in program_scores})

    def get_rated_count(self, obj) -> int:
        if self.context.get("managed_evaluation"):
            return len(self.get_rated_experts(obj))
        rated_attr = getattr(obj, "rated_count", None)
        if rated_attr is not None:
            return rated_attr
        program_scores = self._get_program_scores(obj)
        return len({score.user_id for score in program_scores})

    def get_max_rates(self, obj):
        return self.context.get("program_max_rates")
