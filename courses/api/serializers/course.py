from rest_framework import serializers

from courses.models import (
    CourseAccessType,
    CourseContentStatus,
    ProgressStatus,
)
from courses.services.access import ACTION_CONTINUE, ACTION_LOCK, ACTION_START

from .common import CourseAnalyticsStubSerializer


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
