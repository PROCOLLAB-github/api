from rest_framework import serializers

from courses.models import (
    CourseLessonContentStatus,
    CourseModuleContentStatus,
    ProgressStatus,
)

from .common import LessonTaskSerializer


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
