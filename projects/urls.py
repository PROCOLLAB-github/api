from django.urls import path

from projects.views import (
    ProjectDetail,
    ProjectList,
    ProjectSteps,
    AchievementList,
    AchievementDetail,
    ProjectCollaborators,
    ProjectCountView,
    ProjectVacancyResponses,
)

app_name = "projects"

urlpatterns = [
    path("", ProjectList.as_view()),
    path("<int:pk>/collaborators/", ProjectCollaborators.as_view()),
    path("<int:pk>/", ProjectDetail.as_view()),
    path("count/", ProjectCountView.as_view()),
    path("steps/", ProjectSteps.as_view()),
    path("achievements/", AchievementList.as_view()),
    path("achievements/<int:pk>/", AchievementDetail.as_view()),
    path("<int:pk>/responses/", ProjectVacancyResponses.as_view()),
]
