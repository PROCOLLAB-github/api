# Roadmap: DEV-076, DEV-056

from rest_framework import serializers


class ProgramOverviewProgramSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ProgramOverviewTotalSerializer(serializers.Serializer):
    total = serializers.IntegerField(min_value=0)


class ApplicationStatusCountsSerializer(serializers.Serializer):
    draft = serializers.IntegerField(min_value=0)
    submitted = serializers.IntegerField(min_value=0)
    approved = serializers.IntegerField(min_value=0)
    rejected = serializers.IntegerField(min_value=0)
    withdrawn = serializers.IntegerField(min_value=0)
    cancelled = serializers.IntegerField(min_value=0)


class ParticipationModeCountsSerializer(serializers.Serializer):
    undecided = serializers.IntegerField(min_value=0)
    individual = serializers.IntegerField(min_value=0)
    team = serializers.IntegerField(min_value=0)


class ProgramOverviewApplicationsSerializer(ProgramOverviewTotalSerializer):
    by_status = ApplicationStatusCountsSerializer()
    by_participation_mode = ParticipationModeCountsSerializer()


class ProgramOverviewTeamsSerializer(ProgramOverviewTotalSerializer):
    accepted_members = serializers.IntegerField(min_value=0)


class SubmissionStatusCountsSerializer(serializers.Serializer):
    draft = serializers.IntegerField(min_value=0)
    submitted = serializers.IntegerField(min_value=0)
    returned = serializers.IntegerField(min_value=0)
    final = serializers.IntegerField(min_value=0)
    cancelled = serializers.IntegerField(min_value=0)


class ProgramOverviewSubmissionsSerializer(ProgramOverviewTotalSerializer):
    by_status = SubmissionStatusCountsSerializer()
    applications_with_submitted_solution = serializers.IntegerField(min_value=0)


class AssignmentStatusCountsSerializer(serializers.Serializer):
    assigned = serializers.IntegerField(min_value=0)
    completed = serializers.IntegerField(min_value=0)
    revoked = serializers.IntegerField(min_value=0)


class ProgramOverviewAssignmentsSerializer(ProgramOverviewTotalSerializer):
    by_status = AssignmentStatusCountsSerializer()


class EvaluationStatusCountsSerializer(serializers.Serializer):
    draft = serializers.IntegerField(min_value=0)
    submitted = serializers.IntegerField(min_value=0)


class ProgramOverviewEvaluationsSerializer(ProgramOverviewTotalSerializer):
    by_status = EvaluationStatusCountsSerializer()


class ManagerProgramOverviewSerializer(serializers.Serializer):
    program = ProgramOverviewProgramSerializer()
    registrations = ProgramOverviewTotalSerializer()
    participants = ProgramOverviewTotalSerializer()
    applications = ProgramOverviewApplicationsSerializer()
    teams = ProgramOverviewTeamsSerializer()
    submissions = ProgramOverviewSubmissionsSerializer()
    expert_assignments = ProgramOverviewAssignmentsSerializer()
    evaluations = ProgramOverviewEvaluationsSerializer()


class ManagedProgramSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    draft = serializers.BooleanField()
