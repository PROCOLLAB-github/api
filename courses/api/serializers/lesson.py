from rest_framework import serializers

from courses.models import ProgressStatus

from .common import LessonTaskSerializer


class LessonDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    module_id = serializers.IntegerField()
    course_id = serializers.IntegerField()
    title = serializers.CharField()
    progress_status = serializers.ChoiceField(choices=ProgressStatus.choices)
    percent = serializers.IntegerField(min_value=0, max_value=100)
    current_task_id = serializers.IntegerField(allow_null=True)
    tasks = LessonTaskSerializer(many=True)
