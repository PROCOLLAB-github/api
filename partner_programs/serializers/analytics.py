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
    participant_regions = AnalyticsRegionsSerializer()


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


class AssignmentExpertSerializer(serializers.Serializer):
    expert_id = serializers.IntegerField()
    user_id = serializers.IntegerField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    full_name = serializers.CharField(allow_blank=True)
    avatar = serializers.URLField(allow_null=True)


class AssignmentProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ProgramAssignmentScopeSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=("all", "completed", "pending"), default="all"
    )


class ProgramAssignmentSerializer(serializers.Serializer):
    assignment_id = serializers.IntegerField()
    expert = AssignmentExpertSerializer()
    project = AssignmentProjectSerializer()
    status = serializers.ChoiceField(
        choices=("not_ready", "pending", "in_progress", "completed")
    )
    criteria_total = serializers.IntegerField(min_value=0)
    criteria_scored = serializers.IntegerField(min_value=0)
    assigned_at = serializers.DateTimeField()
    project_submitted = serializers.BooleanField()
    project_submitted_at = serializers.DateTimeField(allow_null=True)
    waiting_since = serializers.DateTimeField(allow_null=True)
    waiting_seconds = serializers.IntegerField(min_value=0, allow_null=True)


class AssignmentCriterionSerializer(serializers.Serializer):
    criterion_id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True, allow_blank=True)
    type = serializers.CharField()
    min_value = serializers.FloatField(allow_null=True)
    max_value = serializers.FloatField(allow_null=True)
    value = serializers.CharField(
        allow_null=True, allow_blank=True, trim_whitespace=False
    )
    is_scored = serializers.BooleanField()


class ProgramAssignmentScoresSerializer(ProgramAssignmentSerializer):
    scores = AssignmentCriterionSerializer(many=True)


class DelayedExpertSerializer(AssignmentExpertSerializer):
    assignments_total = serializers.IntegerField(min_value=0)
    completed = serializers.IntegerField(min_value=0)
    pending = serializers.IntegerField(min_value=0)
    overdue_24h = serializers.IntegerField(min_value=0)
    overdue_48h = serializers.IntegerField(min_value=0)
    oldest_waiting_since = serializers.DateTimeField()
    oldest_waiting_seconds = serializers.IntegerField(min_value=0)
    severity = serializers.ChoiceField(choices=("critical", "warning"))


class DelayedExpertsSerializer(AnalyticsTotalSerializer):
    items = DelayedExpertSerializer(many=True)


class ProjectsNotSubmittedSerializer(AnalyticsTotalSerializer):
    """Несданные связи программы; требование сдачи применимо только к конкурсной."""

    applicable = serializers.BooleanField()


class ProgramAttentionSerializer(serializers.Serializer):
    participants_without_team = serializers.IntegerField(min_value=0)
    projects_awaiting_evaluation = serializers.IntegerField(min_value=0)
    projects_not_submitted = ProjectsNotSubmittedSerializer()
    delayed_experts = DelayedExpertsSerializer()


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
