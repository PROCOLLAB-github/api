from django.urls import path

from core.views import (
    SkillsNestedView,
    SkillsInlineView,
)
from core.notifications import NotificationsView

app_name = "core"

urlpatterns = [
    path("notifications/", NotificationsView.as_view()),
    path("notifications/<str:notification_id>/read/", NotificationsView.as_view()),
    path("skills/nested/", SkillsNestedView.as_view()),
    path("skills/inline/", SkillsInlineView.as_view()),
]
