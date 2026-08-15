from django.urls import path

from notifications.views import (
    NotificationListView,
    NotificationReadAllView,
    NotificationReadView,
    NotificationUnreadCountView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="list"),
    path("unread-count/", NotificationUnreadCountView.as_view(), name="unread-count"),
    path("read-all/", NotificationReadAllView.as_view(), name="read-all"),
    path("<int:notification_id>/read/", NotificationReadView.as_view(), name="read"),
]
