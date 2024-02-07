from django.urls import path

from rate_projects.views import RateProject, RateProjects

urlpatterns = [
    path("rate/", RateProject.as_view()),
    path("<int:program_id>/", RateProjects.as_view())
]