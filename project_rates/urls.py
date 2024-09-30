from django.urls import path

from project_rates.views import (
    RateProject,
    ProjectListForRate,
)

urlpatterns = [
    path("rate/<int:project_id>", RateProject.as_view()),
    path("<int:program_id>", ProjectListForRate.as_view()),
]
