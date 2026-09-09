"""SQL-free, explicit contracts for legacy assignment analytics."""

from rest_framework import serializers


class ProjectAssignmentScopeSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=("all", "completed", "pending"), default="all"
    )


class ProjectAssignmentExpertSerializer(serializers.Serializer):
    expert_id = serializers.IntegerField()
    user_id = serializers.IntegerField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    full_name = serializers.CharField(allow_blank=True)
    avatar = serializers.URLField(allow_null=True)


class ProjectAssignmentProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)


class ProjectAssignmentAnalyticsSerializer(serializers.Serializer):
    assignment_id = serializers.IntegerField()
    expert = ProjectAssignmentExpertSerializer()
    project = ProjectAssignmentProjectSerializer()
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


class ProjectAssignmentCriterionSerializer(serializers.Serializer):
    criterion_id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_null=True, allow_blank=True)
    type = serializers.ChoiceField(choices=("str", "int", "bool", "float"))
    min_value = serializers.FloatField(allow_null=True)
    max_value = serializers.FloatField(allow_null=True)
    value = serializers.CharField(
        allow_null=True, allow_blank=True, trim_whitespace=False
    )
    is_scored = serializers.BooleanField()


class ProjectAssignmentScoresSerializer(ProjectAssignmentAnalyticsSerializer):
    scores = ProjectAssignmentCriterionSerializer(many=True)


class ProjectDelayedExpertSerializer(ProjectAssignmentExpertSerializer):
    assignments_total = serializers.IntegerField(min_value=0)
    completed = serializers.IntegerField(min_value=0)
    pending = serializers.IntegerField(min_value=0)
    overdue_24h = serializers.IntegerField(min_value=0)
    overdue_48h = serializers.IntegerField(min_value=0)
    oldest_waiting_since = serializers.DateTimeField()
    oldest_waiting_seconds = serializers.IntegerField(min_value=0)
    severity = serializers.ChoiceField(choices=("critical", "warning"))


class ProjectDelayedExpertsSerializer(serializers.Serializer):
    total = serializers.IntegerField(min_value=0)
    items = ProjectDelayedExpertSerializer(many=True)
