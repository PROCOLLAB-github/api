# Roadmap: DEV-050, DEV-051, DEV-052, DEV-073
# PII-safe контракты решений и экспертных оценок.

from rest_framework import serializers

from partner_programs.models import (
    Evaluation,
    EvaluationAmendment,
    EvaluationScore,
    PartnerProgram,
    Submission,
    SubmissionExpertAssignment,
)
from project_rates.models import Criteria
from users.models import Expert


class EvaluationScoreWriteSerializer(serializers.Serializer):
    criterion_id = serializers.IntegerField(min_value=1)
    value = serializers.DecimalField(
        max_digits=18,
        decimal_places=6,
        coerce_to_string=False,
    )


class EvaluationDraftCreateSerializer(serializers.Serializer):
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    scores = EvaluationScoreWriteSerializer(
        many=True,
        required=False,
        default=list,
    )


class EvaluationDraftUpdateSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True)
    scores = EvaluationScoreWriteSerializer(many=True, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Передайте comment или scores.")
        return attrs


class EvaluationAmendSerializer(EvaluationDraftUpdateSerializer):
    pass


class ProgramSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerProgram
        fields = ("id", "name")
        read_only_fields = fields


class EvaluationExpertSummarySerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)

    class Meta:
        model = Expert
        fields = ("id", "user_id", "first_name", "last_name")
        read_only_fields = fields


class EvaluationCriterionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Criteria
        fields = (
            "id",
            "name",
            "description",
            "type",
            "min_value",
            "max_value",
        )
        read_only_fields = fields


class EvaluationScoreReadSerializer(serializers.ModelSerializer):
    criterion_id = serializers.IntegerField(read_only=True)
    value = serializers.DecimalField(
        max_digits=18,
        decimal_places=6,
        read_only=True,
    )

    class Meta:
        model = EvaluationScore
        fields = (
            "id",
            "criterion_id",
            "value",
            "criterion_name",
            "criterion_type",
            "min_value",
            "max_value",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class EvaluationReadSerializer(serializers.ModelSerializer):
    submission_id = serializers.IntegerField(read_only=True)
    expert = EvaluationExpertSummarySerializer(read_only=True)
    scores = EvaluationScoreReadSerializer(many=True, read_only=True)

    class Meta:
        model = Evaluation
        fields = (
            "id",
            "submission_id",
            "expert",
            "status",
            "comment",
            "scores",
            "total_score",
            "submitted_at",
            "amended_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ExpertAssignmentSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmissionExpertAssignment
        fields = (
            "id",
            "status",
            "assigned_at",
            "completed_at",
        )
        read_only_fields = fields


class ExpertEvaluationSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True, read_only=True)
    status = serializers.CharField(allow_null=True, read_only=True)
    updated_at = serializers.DateTimeField(allow_null=True, read_only=True)
    submitted_at = serializers.DateTimeField(allow_null=True, read_only=True)
    amended_at = serializers.DateTimeField(allow_null=True, read_only=True)


class ExpertSubmissionListSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="submission_id", read_only=True)
    program = ProgramSummarySerializer(source="submission.program", read_only=True)
    title = serializers.CharField(source="submission.title", read_only=True)
    status = serializers.CharField(
        source="submission.status",
        read_only=True,
    )
    stage_key = serializers.CharField(source="submission.stage_key", read_only=True)
    version = serializers.IntegerField(source="submission.version", read_only=True)
    submitted_at = serializers.DateTimeField(
        source="submission.submitted_at",
        read_only=True,
    )
    assignment = ExpertAssignmentSummarySerializer(source="*", read_only=True)
    my_evaluation = serializers.SerializerMethodField()

    class Meta:
        model = SubmissionExpertAssignment
        fields = (
            "id",
            "program",
            "title",
            "status",
            "stage_key",
            "version",
            "submitted_at",
            "assignment",
            "my_evaluation",
        )
        read_only_fields = fields

    def get_my_evaluation(self, assignment):
        if assignment.my_evaluation_id is None:
            return None
        return {
            "id": assignment.my_evaluation_id,
            "status": assignment.my_evaluation_status,
            "updated_at": assignment.my_evaluation_updated_at,
            "submitted_at": assignment.my_evaluation_submitted_at,
            "amended_at": assignment.my_evaluation_amended_at,
        }


class ExpertSubmissionDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="submission.id", read_only=True)
    program = ProgramSummarySerializer(source="submission.program", read_only=True)
    title = serializers.CharField(source="submission.title", read_only=True)
    description = serializers.CharField(
        source="submission.description",
        read_only=True,
    )
    links = serializers.JSONField(source="submission.links", read_only=True)
    status = serializers.CharField(source="submission.status", read_only=True)
    stage_key = serializers.CharField(
        source="submission.stage_key",
        read_only=True,
    )
    version = serializers.IntegerField(source="submission.version", read_only=True)
    submitted_at = serializers.DateTimeField(
        source="submission.submitted_at",
        read_only=True,
    )
    assignment = ExpertAssignmentSummarySerializer(read_only=True)
    my_evaluation = EvaluationReadSerializer(
        source="evaluation",
        allow_null=True,
        read_only=True,
    )
    criteria = EvaluationCriterionSerializer(many=True, read_only=True)


class ExpertSubmissionFilterSerializer(serializers.Serializer):
    program_id = serializers.IntegerField(min_value=1, required=False)
    submission_status = serializers.ChoiceField(
        choices=Submission.STATUS_CHOICES,
        required=False,
    )
    evaluation_status = serializers.ChoiceField(
        choices=(
            (Evaluation.STATUS_DRAFT, Evaluation.STATUS_DRAFT),
            (Evaluation.STATUS_SUBMITTED, Evaluation.STATUS_SUBMITTED),
            ("none", "none"),
        ),
        required=False,
    )


class ManagerEvaluationFilterSerializer(serializers.Serializer):
    submission_id = serializers.IntegerField(min_value=1, required=False)
    expert_id = serializers.IntegerField(min_value=1, required=False)
    evaluation_status = serializers.ChoiceField(
        choices=Evaluation.STATUS_CHOICES,
        required=False,
    )
    assignment_status = serializers.ChoiceField(
        choices=SubmissionExpertAssignment.STATUS_CHOICES,
        required=False,
    )
    stage_key = serializers.CharField(max_length=128, required=False)


class ManagerSubmissionSummarySerializer(serializers.ModelSerializer):
    program = ProgramSummarySerializer(read_only=True)

    class Meta:
        model = Submission
        fields = (
            "id",
            "program",
            "title",
            "status",
            "stage_key",
            "version",
            "submitted_at",
        )
        read_only_fields = fields


class ManagerEvaluationSerializer(serializers.ModelSerializer):
    submission = ManagerSubmissionSummarySerializer(read_only=True)
    expert = EvaluationExpertSummarySerializer(read_only=True)
    assignment = serializers.SerializerMethodField()
    scores = EvaluationScoreReadSerializer(many=True, read_only=True)

    class Meta:
        model = Evaluation
        fields = (
            "id",
            "status",
            "submission",
            "expert",
            "assignment",
            "scores",
            "comment",
            "total_score",
            "submitted_at",
            "amended_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_assignment(self, evaluation):
        if not hasattr(evaluation, "assignment_id") or evaluation.assignment_id is None:
            return None
        return {
            "id": evaluation.assignment_id,
            "status": evaluation.assignment_status,
            "assigned_at": evaluation.assignment_assigned_at,
            "completed_at": evaluation.assignment_completed_at,
        }


class EvaluationAmendmentSerializer(serializers.ModelSerializer):
    evaluation_id = serializers.IntegerField(read_only=True)
    changed_by_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = EvaluationAmendment
        fields = (
            "id",
            "evaluation_id",
            "changed_by_id",
            "previous_comment",
            "comment",
            "previous_scores",
            "scores",
            "previous_total_score",
            "total_score",
            "created_at",
        )
        read_only_fields = fields
