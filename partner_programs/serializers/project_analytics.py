"""SQL-free contract for legacy Project analytics, not production Applications."""

from rest_framework import serializers

from partner_programs.serializers.project_assignment_analytics import (
    ProjectDelayedExpertsSerializer,
)


class ProjectAnalyticsTotalSerializer(serializers.Serializer):
    total = serializers.IntegerField(min_value=0)


class ProjectAnalyticsRegionSerializer(serializers.Serializer):
    name = serializers.CharField()
    count = serializers.IntegerField(min_value=0)


class ProjectAnalyticsRegionsSerializer(ProjectAnalyticsTotalSerializer):
    items = ProjectAnalyticsRegionSerializer(many=True)


class ProjectAnalyticsSummarySerializer(serializers.Serializer):
    participants = ProjectAnalyticsTotalSerializer()
    projects = ProjectAnalyticsTotalSerializer()
    experts = ProjectAnalyticsTotalSerializer()
    regions = ProjectAnalyticsRegionsSerializer()
    participant_regions = ProjectAnalyticsRegionsSerializer()


class ProjectAnalyticsParticipantFunnelSerializer(serializers.Serializer):
    registrations = serializers.IntegerField(min_value=0)
    unique_participants = serializers.IntegerField(min_value=0)
    with_team = serializers.IntegerField(min_value=0)
    project_creators = serializers.IntegerField(min_value=0)
    submitted_project_creators = serializers.IntegerField(min_value=0)


class ProjectAnalyticsSolutionFunnelSerializer(serializers.Serializer):
    created = serializers.IntegerField(min_value=0)
    not_submitted = serializers.IntegerField(min_value=0)
    submitted = serializers.IntegerField(min_value=0)
    evaluated = serializers.IntegerField(min_value=0)


class ProjectAnalyticsAssignmentsSerializer(serializers.Serializer):
    total = serializers.IntegerField(min_value=0)
    pending = serializers.IntegerField(min_value=0)
    evaluated = serializers.IntegerField(min_value=0)


class ProjectAnalyticsProjectsSerializer(serializers.Serializer):
    submitted = serializers.IntegerField(min_value=0)
    awaiting_evaluation = serializers.IntegerField(min_value=0)
    partially_evaluated = serializers.IntegerField(min_value=0)
    evaluated = serializers.IntegerField(min_value=0)


class ProjectAnalyticsEvaluationSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=("open", "distributed"))
    max_evaluations_per_project = serializers.IntegerField(min_value=1, allow_null=True)
    assignments = ProjectAnalyticsAssignmentsSerializer()
    projects = ProjectAnalyticsProjectsSerializer()


class ProjectAnalyticsAttentionSerializer(serializers.Serializer):
    participants_without_team = serializers.IntegerField(min_value=0)
    projects_awaiting_evaluation = serializers.IntegerField(min_value=0)
    delayed_experts = ProjectDelayedExpertsSerializer()


class ProjectAnalyticsActivitySerializer(serializers.Serializer):
    date = serializers.DateField()
    registrations = serializers.IntegerField(min_value=0)
    submitted_solutions = serializers.IntegerField(min_value=0)


class ProjectAnalyticsSerializer(serializers.Serializer):
    summary = ProjectAnalyticsSummarySerializer()
    participant_funnel = ProjectAnalyticsParticipantFunnelSerializer()
    solution_funnel = ProjectAnalyticsSolutionFunnelSerializer()
    evaluation_status = ProjectAnalyticsEvaluationSerializer()
    attention = ProjectAnalyticsAttentionSerializer()
    activity = ProjectAnalyticsActivitySerializer(many=True)
