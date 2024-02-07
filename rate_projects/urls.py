from django.urls import path

from rate_projects.views import RateProject

urlpatterns = [
    path("rate/", RateProject.as_view())
]