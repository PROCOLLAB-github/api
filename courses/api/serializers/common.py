from rest_framework import serializers

from courses.models import (
    CourseTaskAnswerType,
    CourseTaskCheckType,
    CourseTaskContentStatus,
    CourseTaskInformationalType,
    CourseTaskKind,
    CourseTaskQuestionType,
)


class CourseAnalyticsStubSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(default=False)
    title = serializers.CharField(default="Аналитика")
    state = serializers.ChoiceField(choices=("coming_soon",), default="coming_soon")
    text = serializers.CharField(default="пока закрыто")


class CourseTaskOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order = serializers.IntegerField(min_value=1)
    text = serializers.CharField()


class LessonTaskSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order = serializers.IntegerField(min_value=1)
    title = serializers.CharField()
    answer_title = serializers.CharField(allow_blank=True)
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
