from django.db.models import Prefetch

from courses.models import (
    Course,
    CourseContentStatus,
    CourseLesson,
    CourseLessonContentStatus,
)


def published_course_queryset():
    return Course.objects.exclude(status=CourseContentStatus.DRAFT)


def published_lessons_prefetch():
    return Prefetch(
        "lessons",
        queryset=CourseLesson.objects.filter(
            status=CourseLessonContentStatus.PUBLISHED
        ).order_by("order", "id"),
    )
