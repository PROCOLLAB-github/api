from rest_framework import serializers


class AnalyticsTotalSerializer(serializers.Serializer):
    total = serializers.IntegerField(min_value=0)


class AnalyticsRegionItemSerializer(serializers.Serializer):
    name = serializers.CharField()
    count = serializers.IntegerField(min_value=0)


class AnalyticsRegionsSerializer(AnalyticsTotalSerializer):
    items = AnalyticsRegionItemSerializer(many=True)


class ProgramAnalyticsSummarySerializer(serializers.Serializer):
    participants = AnalyticsTotalSerializer()
    projects = AnalyticsTotalSerializer()
    experts = AnalyticsTotalSerializer()
    regions = AnalyticsRegionsSerializer()


class ProgramParticipantFunnelSerializer(serializers.Serializer):
    registrations = serializers.IntegerField(min_value=0)
    unique_participants = serializers.IntegerField(min_value=0)
    with_team = serializers.IntegerField(min_value=0)
    project_creators = serializers.IntegerField(min_value=0)
    submitted_project_creators = serializers.IntegerField(min_value=0)


class ProgramSolutionFunnelSerializer(serializers.Serializer):
    created = serializers.IntegerField(min_value=0)
    not_submitted = serializers.IntegerField(min_value=0)
    submitted = serializers.IntegerField(min_value=0)
    evaluated = serializers.IntegerField(min_value=0)


class ProgramAssignmentEvaluationSerializer(serializers.Serializer):
    total = serializers.IntegerField(min_value=0)
    pending = serializers.IntegerField(min_value=0)
    evaluated = serializers.IntegerField(min_value=0)


class ProgramProjectEvaluationSerializer(serializers.Serializer):
    submitted = serializers.IntegerField(min_value=0)
    awaiting_evaluation = serializers.IntegerField(min_value=0)
    partially_evaluated = serializers.IntegerField(min_value=0)
    evaluated = serializers.IntegerField(min_value=0)


class ProgramEvaluationStatusSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=("open", "distributed"))
    max_evaluations_per_project = serializers.IntegerField(
        min_value=1,
        allow_null=True,
    )
    assignments = ProgramAssignmentEvaluationSerializer()
    projects = ProgramProjectEvaluationSerializer()


class ProgramAttentionSerializer(serializers.Serializer):
    participants_without_team = serializers.IntegerField(min_value=0)
    projects_awaiting_evaluation = serializers.IntegerField(min_value=0)


class ProgramActivityItemSerializer(serializers.Serializer):
    date = serializers.DateField()
    registrations = serializers.IntegerField(min_value=0)
    submitted_solutions = serializers.IntegerField(min_value=0)


class ProgramManagerAnalyticsSerializer(serializers.Serializer):
    summary = ProgramAnalyticsSummarySerializer()
    participant_funnel = ProgramParticipantFunnelSerializer()
    solution_funnel = ProgramSolutionFunnelSerializer()
    evaluation_status = ProgramEvaluationStatusSerializer()
    attention = ProgramAttentionSerializer()
    activity = ProgramActivityItemSerializer(many=True)
