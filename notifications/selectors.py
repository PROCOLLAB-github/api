from django.conf import settings

from notifications.models import Notification


ANGULAR_NOTIFICATION_TYPES = (
    Notification.Type.PROJECT_INVITE_CREATED,
    Notification.Type.PROJECT_INVITE_ACCEPTED,
    Notification.Type.PROJECT_INVITE_DECLINED,
    Notification.Type.PROJECT_INVITE_REVOKED,
    Notification.Type.VACANCY_RESPONSE_CREATED,
    Notification.Type.VACANCY_RESPONSE_ACCEPTED,
    Notification.Type.VACANCY_RESPONSE_DECLINED,
    Notification.Type.PROGRAM_NEWS_PUBLISHED,
    Notification.Type.PROGRAM_MATERIAL_PUBLISHED,
    Notification.Type.COURSE_ACCESS_OPENED,
)


def get_visible_notifications(user):
    """Returns the notification surface available to the current frontend."""
    queryset = Notification.objects.filter(recipient=user)
    if settings.NEXTGEN_SURFACE_ENABLED:
        return queryset
    return queryset.filter(type__in=ANGULAR_NOTIFICATION_TYPES)
