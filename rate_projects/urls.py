from django.urls import path

from rate_projects.views import RateProject

urlpatterns = [path("rate/<int:project_id>", RateProject.as_view())]
