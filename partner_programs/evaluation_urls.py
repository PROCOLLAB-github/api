# Roadmap: DEV-073

from django.urls import path

from partner_programs.evaluation_views import (
    EvaluationAmendmentListView,
    EvaluationAmendView,
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
    path(
        "<int:evaluation_id>/amend/",
        EvaluationAmendView.as_view(),
        name="amend",
    ),
    path(
        "<int:evaluation_id>/amendments/",
        EvaluationAmendmentListView.as_view(),
        name="amendment-list",
    ),
]
