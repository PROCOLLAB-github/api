from django.urls import path

from partner_programs.evaluation_views import EvaluationCreateView, MyEvaluationView
from partner_programs.submission_views import (
    SubmissionCancelView,
    SubmissionDetailView,
    SubmissionSubmitView,
)

app_name = "submissions"

urlpatterns = [
    path(
        "<int:submission_id>/evaluations/my/",
        MyEvaluationView.as_view(),
        name="my-evaluation",
    ),
    path(
        "<int:submission_id>/evaluations/",
        EvaluationCreateView.as_view(),
        name="evaluation-create",
    ),
    path("<int:submission_id>/", SubmissionDetailView.as_view(), name="detail"),
    path(
        "<int:submission_id>/submit/",
        SubmissionSubmitView.as_view(),
        name="submit",
    ),
    path(
        "<int:submission_id>/cancel/",
        SubmissionCancelView.as_view(),
        name="cancel",
    ),
]
