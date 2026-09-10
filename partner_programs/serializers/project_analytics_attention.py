"""Explicit SQL-free contracts for legacy Project analytics attention lists."""

from rest_framework import serializers


def participant_name(user_id, first_name, last_name):
    name = " ".join(
        part.strip() for part in (first_name, last_name) if part and part.strip()
    )
    return name or f"Участник №{user_id}"


class ProjectAnalyticsAttentionQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=25)
    offset = serializers.IntegerField(min_value=0, default=0)
    search = serializers.CharField(allow_blank=True, default="", trim_whitespace=True)


class ProjectAnalyticsParticipantSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    full_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    registered_at = serializers.DateTimeField(allow_null=True)

    def get_full_name(self, row):
        return participant_name(
            row["user_id"], row["user__first_name"], row["user__last_name"]
        )

    def get_avatar(self, row):
        return row["user__avatar"] or None

    def get_city(self, row):
        return row["user__city"] or None


class ProjectAnalyticsProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)


class ProjectAnalyticsLeaderSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(source="id")
    full_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    def get_full_name(self, user):
        return participant_name(user.pk, user.first_name, user.last_name)

    def get_avatar(self, user):
        return user.avatar or None


WAITING_REASONS = {
    "no_assignments": "Эксперты не назначены",
    "no_completed_evaluations": "Нет завершённых оценок",
    "partially_evaluated": "Частично оценено",
    "awaiting_first_evaluation": "Ожидает первой оценки",
}


class ProjectAnalyticsAwaitingProjectSerializer(serializers.Serializer):
    program_project_id = serializers.IntegerField(source="pk")
    project = ProjectAnalyticsProjectSerializer()
    leader = ProjectAnalyticsLeaderSerializer(source="project.leader", allow_null=True)
    submitted_at = serializers.DateTimeField(source="datetime_submitted", allow_null=True)
    status = serializers.ChoiceField(
        choices=("awaiting_evaluation", "partially_evaluated")
    )
    reason = serializers.ChoiceField(choices=tuple(WAITING_REASONS))
    reason_label = serializers.SerializerMethodField()
    assignments_total = serializers.IntegerField(min_value=0, allow_null=True)
    assignments_completed = serializers.IntegerField(min_value=0, allow_null=True)

    def get_reason_label(self, link):
        return WAITING_REASONS[link.reason]


class ProjectAnalyticsNotSubmittedProjectSerializer(serializers.Serializer):
    program_project_id = serializers.IntegerField(source="pk")
    project = ProjectAnalyticsProjectSerializer()
    leader = ProjectAnalyticsLeaderSerializer(source="project.leader", allow_null=True)
    linked_at = serializers.DateTimeField(source="datetime_created")


class ProjectAnalyticsNotSubmittedMetadataSerializer(serializers.Serializer):
    applicable = serializers.BooleanField()
    submission_deadline = serializers.DateTimeField(allow_null=True)
    submission_open = serializers.BooleanField()
