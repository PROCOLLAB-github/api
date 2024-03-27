from django.urls import path

from core.views import (
    SkillsNestedView,
    SkillsInlineView,
)

app_name = "core"

urlpatterns = [
    path("skills/nested/", SkillsNestedView.as_view()),
    path("skills/inline/", SkillsInlineView.as_view()),
]
