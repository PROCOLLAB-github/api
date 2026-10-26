"""Минимальный контракт виджета; отсутствующие метрики не превращаются в нули."""

from rest_framework import serializers


class WidgetProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)
    program_link_id = serializers.IntegerField()


class ParticipantWidgetSerializer(serializers.Serializer):
    participant_project = WidgetProjectSerializer(allow_null=True)
    case_provided = serializers.BooleanField()
    case_name = serializers.CharField(allow_null=True, allow_blank=True)
    stage = serializers.ChoiceField(
        choices=(
            "none",
            "not_submitted",
            "submitted",
            "review",
            "evaluated",
            "not_applicable",
        )
    )
    submission_open = serializers.BooleanField()


class OrganizerWidgetSerializer(serializers.Serializer):
    participants = serializers.IntegerField(min_value=0)
    projects = serializers.IntegerField(min_value=0)
    submitted_solutions = serializers.IntegerField(min_value=0, allow_null=True)
    participants_without_project = serializers.IntegerField(min_value=0)


class ExpertWidgetSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=("open", "distributed"))
    assigned = serializers.IntegerField(min_value=0, allow_null=True)
    remaining = serializers.IntegerField(min_value=0, allow_null=True)
    evaluation_ends = serializers.DateTimeField(allow_null=True)


class ProgramRoleWidgetSerializer(serializers.Serializer):
    program_id = serializers.IntegerField()
    role = serializers.ChoiceField(choices=("organizer", "expert", "participant"))
    is_competitive = serializers.BooleanField()
    participant = ParticipantWidgetSerializer(required=False)
    organizer = OrganizerWidgetSerializer(required=False)
    expert = ExpertWidgetSerializer(required=False)


class WidgetSolutionRefSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("solution",))
    program_id = serializers.IntegerField(min_value=1)
    solution_id = serializers.IntegerField(min_value=1)
    name = serializers.CharField()


class SolutionParticipantWidgetSerializer(ParticipantWidgetSerializer):
    participant_project = None
    application = WidgetSolutionRefSerializer(allow_null=True)


class SolutionOrganizerWidgetSerializer(serializers.Serializer):
    participants = serializers.IntegerField(min_value=0)
    solutions = serializers.IntegerField(min_value=0)
    submitted_solutions = serializers.IntegerField(min_value=0, allow_null=True)
    participants_without_solution = serializers.IntegerField(min_value=0)


class SolutionProgramRoleWidgetSerializer(ProgramRoleWidgetSerializer):
    storage_mode = serializers.ChoiceField(choices=("solution",))
    participant = SolutionParticipantWidgetSerializer(required=False)
    organizer = SolutionOrganizerWidgetSerializer(required=False)
