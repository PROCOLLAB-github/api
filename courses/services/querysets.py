from django.db.models import Count, Prefetch, Q

from courses.models import (
    Course,
    CourseContentStatus,
    CourseLesson,
    CourseLessonContentStatus,
    CourseTaskContentStatus,
)


def published_course_queryset():
    return Course.objects.exclude(status=CourseContentStatus.DRAFT)


def published_lessons_prefetch():
    return Prefetch(
        "lessons",
        queryset=CourseLesson.objects.filter(
            status=CourseLessonContentStatus.PUBLISHED
        )
        .annotate(
            task_count=Count(
                "tasks",
                filter=Q(tasks__status=CourseTaskContentStatus.PUBLISHED),
            )
        )
        .order_by("order", "id"),
    )
