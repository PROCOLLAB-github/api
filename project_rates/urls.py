from django.urls import path

from project_rates.views import RateProject, RateProjects, RateProjectsDetails

urlpatterns = [
    path("rate/<int:project_id>", RateProject.as_view()),
    path("<int:program_id>", RateProjects.as_view()),
    path("details/<int:project_id>", RateProjectsDetails.as_view()),
]
