from rest_framework import serializers

from courses.models import (
    CourseAccessType,
    CourseContentStatus,
    CourseLessonContentStatus,
    CourseModuleContentStatus,
    CourseTaskAnswerType,
    CourseTaskCheckType,
    CourseTaskContentStatus,
    CourseTaskInformationalType,
    CourseTaskKind,
    CourseTaskQuestionType,
    ProgressStatus,
    UserTaskAnswerStatus,
)
from courses.services.access import ACTION_CONTINUE, ACTION_LOCK, ACTION_START
from courses.services.answers import TaskAnswerSubmitPayload


class CourseAnalyticsStubSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(default=False)
    title = serializers.CharField(default="Аналитика")
    state = serializers.ChoiceField(choices=("coming_soon",), default="coming_soon")
    text = serializers.CharField(default="пока закрыто")


class CourseCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    partner_program_id = serializers.IntegerField(allow_null=True)
    title = serializers.CharField()
    access_type = serializers.ChoiceField(choices=CourseAccessType.choices)
    status = serializers.ChoiceField(choices=CourseContentStatus.choices)
    avatar_url = serializers.URLField(allow_null=True)
    card_cover_url = serializers.URLField(allow_null=True)
    start_date = serializers.DateField(allow_null=True)
    end_date = serializers.DateField(allow_null=True)
    date_label = serializers.CharField()
    is_available = serializers.BooleanField()
    action_state = serializers.ChoiceField(
        choices=(ACTION_START, ACTION_CONTINUE, ACTION_LOCK)
    )
    progress_status = serializers.ChoiceField(choices=ProgressStatus.choices)
    percent = serializers.IntegerField(min_value=0, max_value=100)


class CourseDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    partner_program_id = serializers.IntegerField(allow_null=True)
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    access_type = serializers.ChoiceField(choices=CourseAccessType.choices)
    status = serializers.ChoiceField(choices=CourseContentStatus.choices)
    avatar_url = serializers.URLField(allow_null=True)
    header_cover_url = serializers.URLField(allow_null=True)
    start_date = serializers.DateField(allow_null=True)
    end_date = serializers.DateField(allow_null=True)
    date_label = serializers.CharField()
    is_available = serializers.BooleanField()
    progress_status = serializers.ChoiceField(choices=ProgressStatus.choices)
    percent = serializers.IntegerField(min_value=0, max_value=100)
    analytics_stub = CourseAnalyticsStubSerializer()


class CourseTaskOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order = serializers.IntegerField(min_value=1)
    text = serializers.CharField()


class LessonTaskSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order = serializers.IntegerField(min_value=1)
    title = serializers.CharField()
    status = serializers.ChoiceField(choices=CourseTaskContentStatus.choices)
    task_kind = serializers.ChoiceField(choices=CourseTaskKind.choices)
    check_type = serializers.ChoiceField(
        choices=CourseTaskCheckType.choices,
        allow_null=True,
    )
    informational_type = serializers.ChoiceField(
        choices=CourseTaskInformationalType.choices,
        allow_null=True,
    )
    question_type = serializers.ChoiceField(
        choices=CourseTaskQuestionType.choices,
        allow_null=True,
    )
    answer_type = serializers.ChoiceField(
        choices=CourseTaskAnswerType.choices,
        allow_null=True,
    )
    body_text = serializers.CharField(allow_blank=True)
    video_url = serializers.URLField(allow_null=True)
    image_url = serializers.URLField(allow_null=True)
    attachment_url = serializers.URLField(allow_null=True)
    is_available = serializers.BooleanField(default=False)
    is_completed = serializers.BooleanField(default=False)
    options = CourseTaskOptionSerializer(many=True, required=False)


class CourseLessonStructureSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    module_id = serializers.IntegerField()
    title = serializers.CharField()
    order = serializers.IntegerField(min_value=1)
    task_count = serializers.IntegerField(min_value=0)
    status = serializers.ChoiceField(choices=CourseLessonContentStatus.choices)
    is_available = serializers.BooleanField()
    progress_status = serializers.ChoiceField(choices=ProgressStatus.choices)
    percent = serializers.IntegerField(min_value=0, max_value=100)
    current_task_id = serializers.IntegerField(allow_null=True, required=False)
    tasks = LessonTaskSerializer(many=True, required=False)


class CourseModuleStructureSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    course_id = serializers.IntegerField()
    title = serializers.CharField()
    order = serializers.IntegerField(min_value=1)
    avatar_url = serializers.URLField(allow_null=True)
    start_date = serializers.DateField()
    status = serializers.ChoiceField(choices=CourseModuleContentStatus.choices)
    is_available = serializers.BooleanField()
    progress_status = serializers.ChoiceField(choices=ProgressStatus.choices)
    percent = serializers.IntegerField(min_value=0, max_value=100)
    lessons = CourseLessonStructureSerializer(many=True, required=False)


class CourseStructureSerializer(serializers.Serializer):
    course_id = serializers.IntegerField()
    partner_program_id = serializers.IntegerField(allow_null=True)
    progress_status = serializers.ChoiceField(choices=ProgressStatus.choices)
    percent = serializers.IntegerField(min_value=0, max_value=100)
    modules = CourseModuleStructureSerializer(many=True)


class LessonDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    module_id = serializers.IntegerField()
    course_id = serializers.IntegerField()
    title = serializers.CharField()
    progress_status = serializers.ChoiceField(choices=ProgressStatus.choices)
    percent = serializers.IntegerField(min_value=0, max_value=100)
    current_task_id = serializers.IntegerField(allow_null=True)
    tasks = LessonTaskSerializer(many=True)


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
