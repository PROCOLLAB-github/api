from django.urls import path

from project_rates.views import (
    RateProject,
    RateProjects,
    RateProjectsDetails,
    ScoredProjects,
)

urlpatterns = [
    path("rate/<int:project_id>", RateProject.as_view()),
    path("<int:program_id>", RateProjects.as_view()),
    path("scored/<int:program_id>", ScoredProjects.as_view()),
    path("details", RateProjectsDetails.as_view()),
]
