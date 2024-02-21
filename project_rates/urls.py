from django.urls import path

from project_rates.views import RateProject, RateProjects


urlpatterns = [
    path("rate/", RateProject.as_view()),
    path("<int:program_id>", RateProjects.as_view()),
]
