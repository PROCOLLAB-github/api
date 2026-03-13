from django.shortcuts import get_object_or_404

from courses.models import UserCourseProgress
from courses.services.access import resolve_course_card_state
from courses.services.progress import progress_payload
from courses.services.querysets import published_course_queryset


def build_course_detail_payload(user, pk: int) -> dict:
    course = get_object_or_404(
        published_course_queryset().select_related(
            "partner_program",
            "avatar_file",
            "header_cover_file",
        ),
        pk=pk,
    )
    progress = UserCourseProgress.objects.filter(user=user, course=course).first()
    normalized_progress = progress_payload(progress)
    card_state = resolve_course_card_state(course, user, progress=progress)

    return {
        "id": course.id,
        "partner_program_id": course.partner_program_id,
        "title": course.title,
        "description": course.description,
        "access_type": course.access_type,
        "status": course.status,
        "avatar_url": course.avatar_file_id,
        "header_cover_url": course.header_cover_file_id,
        "start_date": course.start_date,
        "end_date": course.end_date,
        "date_label": card_state.date_label,
        "is_available": card_state.is_available,
        "progress_status": normalized_progress["status"],
        "percent": normalized_progress["percent"],
        "analytics_stub": {
            "enabled": False,
            "title": "Аналитика",
            "state": "coming_soon",
            "text": "пока закрыто",
        },
    }
