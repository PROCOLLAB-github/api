from django.urls import path

from partner_programs.evaluation_views import (
    EvaluationDetailView,
    EvaluationSubmitView,
)

app_name = "evaluations"

urlpatterns = [
    path("<int:evaluation_id>/", EvaluationDetailView.as_view(), name="detail"),
    path(
        "<int:evaluation_id>/submit/",
        EvaluationSubmitView.as_view(),
        name="submit",
    ),
]
