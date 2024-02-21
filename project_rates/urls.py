from django.urls import path

from project_rates.views import RateProject

urlpatterns = [path("rate/<int:project_id>", RateProject.as_view())]
