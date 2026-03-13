from courses.models import UserCourseProgress
from courses.services.access import resolve_course_card_state
from courses.services.progress import progress_payload
from courses.services.querysets import published_course_queryset


def build_course_list_payload(user) -> list[dict]:
    courses = list(
        published_course_queryset()
        .select_related("partner_program", "avatar_file", "card_cover_file")
        .order_by("-datetime_created")
    )
    progress_map = {
        progress.course_id: progress
        for progress in UserCourseProgress.objects.filter(
            user=user,
            course_id__in=[course.id for course in courses],
        )
    }

    data = []
    for course in courses:
        progress = progress_map.get(course.id)
        card_state = resolve_course_card_state(course, user, progress=progress)
        normalized_progress = progress_payload(progress)
        data.append(
            {
                "id": course.id,
                "partner_program_id": course.partner_program_id,
                "title": course.title,
                "access_type": course.access_type,
                "status": course.status,
                "avatar_url": course.avatar_file_id,
                "card_cover_url": course.card_cover_file_id,
                "start_date": course.start_date,
                "end_date": course.end_date,
                "date_label": card_state.date_label,
                "is_available": card_state.is_available,
                "action_state": card_state.action_state,
                "progress_status": normalized_progress["status"],
                "percent": normalized_progress["percent"],
            }
        )
    return data
