from django.urls import path

from partner_programs.evaluation_views import (
    ExpertSubmissionDetailView,
    ExpertSubmissionListView,
)

app_name = "expert_submissions"

urlpatterns = [
    path("submissions/", ExpertSubmissionListView.as_view(), name="list"),
    path(
        "submissions/<int:submission_id>/",
        ExpertSubmissionDetailView.as_view(),
        name="detail",
    ),
]
