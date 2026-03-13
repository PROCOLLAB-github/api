from rest_framework import serializers

from courses.models import UserTaskAnswerStatus
from courses.services.answers import TaskAnswerSubmitPayload


class TaskAnswerSubmitSerializer(serializers.Serializer):
    answer_text = serializers.CharField(required=False, allow_blank=True, default="")
    option_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        default=list,
    )
    file_ids = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        default=list,
    )

    def validate_option_ids(self, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise serializers.ValidationError(
                "Поле option_ids содержит повторяющиеся значения."
            )
        return value

    def validate_file_ids(self, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise serializers.ValidationError(
                "Поле file_ids содержит повторяющиеся значения."
            )
        return value

    def to_payload(self) -> TaskAnswerSubmitPayload:
        data = self.validated_data
        return TaskAnswerSubmitPayload(
            answer_text=data.get("answer_text", ""),
            option_ids=data.get("option_ids", []),
            file_ids=data.get("file_ids", []),
        )


class TaskAnswerSubmitResultSerializer(serializers.Serializer):
    answer_id = serializers.IntegerField(source="answer.id")
    status = serializers.ChoiceField(
        choices=UserTaskAnswerStatus.choices,
        source="answer.status",
    )
    is_correct = serializers.BooleanField(allow_null=True)
    can_continue = serializers.BooleanField()
    next_task_id = serializers.IntegerField(allow_null=True)
    submitted_at = serializers.DateTimeField(source="answer.submitted_at")


class CourseVisitSerializer(serializers.Serializer):
    pass


class CourseVisitResultSerializer(serializers.Serializer):
    last_visit_at = serializers.DateTimeField()
