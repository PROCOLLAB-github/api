from rest_framework import serializers

from partner_programs.models import (
    Evaluation,
    Submission,
    SubmissionExpertAssignment,
)
from users.models import Expert


class SubmissionAssignmentSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submission
        fields = (
            "id",
            "title",
            "status",
            "stage_key",
            "version",
            "submitted_at",
        )
        read_only_fields = fields


class SubmissionAssignmentExpertSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)

    class Meta:
        model = Expert
        fields = (
            "id",
            "user_id",
            "first_name",
            "last_name",
        )
        read_only_fields = fields


class SubmissionAssignmentReadSerializer(serializers.ModelSerializer):
    submission = SubmissionAssignmentSubmissionSerializer(read_only=True)
    expert = SubmissionAssignmentExpertSerializer(read_only=True)
    assigned_by_id = serializers.IntegerField(read_only=True)
    revoked_by_id = serializers.IntegerField(read_only=True)
    evaluation_status = serializers.SerializerMethodField()
    evaluation = serializers.SerializerMethodField()

    class Meta:
        model = SubmissionExpertAssignment
        fields = (
            "id",
            "status",
            "submission",
            "expert",
            "assigned_by_id",
            "assigned_at",
            "completed_at",
            "revoked_by_id",
            "revoked_at",
            "revoke_reason",
            "evaluation_status",
            "evaluation",
        )
        read_only_fields = fields

    def get_evaluation_status(self, assignment):
        if hasattr(assignment, "annotated_evaluation_status"):
            return assignment.annotated_evaluation_status
        return (
            Evaluation.objects.filter(
                submission_id=assignment.submission_id,
                expert_id=assignment.expert_id,
            )
            .values_list("status", flat=True)
            .first()
        )

    def get_evaluation(self, assignment):
        if not hasattr(assignment, "annotated_evaluation_id"):
            evaluation = (
                Evaluation.objects.filter(
                    submission_id=assignment.submission_id,
                    expert_id=assignment.expert_id,
                )
                .values(
                    "id",
                    "status",
                    "updated_at",
                    "submitted_at",
                    "total_score",
                )
                .first()
            )
            return evaluation
        if assignment.annotated_evaluation_id is None:
            return None
        return {
            "id": assignment.annotated_evaluation_id,
            "status": assignment.annotated_evaluation_status,
            "updated_at": assignment.annotated_evaluation_updated_at,
            "submitted_at": assignment.annotated_evaluation_submitted_at,
            "total_score": assignment.annotated_evaluation_total_score,
        }


class SubmissionAssignmentCreateSerializer(serializers.Serializer):
    submission_id = serializers.IntegerField(min_value=1, write_only=True)
    expert_id = serializers.IntegerField(min_value=1, write_only=True)


class SubmissionAssignmentRevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
        write_only=True,
    )


class SubmissionAssignmentFilterSerializer(serializers.Serializer):
    submission_id = serializers.IntegerField(min_value=1, required=False)
    expert_id = serializers.IntegerField(min_value=1, required=False)
    status = serializers.ChoiceField(
        choices=SubmissionExpertAssignment.STATUS_CHOICES,
        required=False,
    )
