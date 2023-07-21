from django.urls import path

from news.views import NewsList, NewsDetail
from projects.views import (
    ProjectDetail,
    ProjectList,
    ProjectSteps,
    AchievementList,
    AchievementDetail,
    ProjectCollaborators,
    ProjectCountView,
    ProjectVacancyResponses,
    ProjectRecommendedUsers,
    SetLikeOnProject,
    ProjectNewsDetailSetViewed,
    ProjectNewsDetailSetLiked,
)

app_name = "projects"

urlpatterns = [
    path("", ProjectList.as_view()),
    path("<int:pk>/like/", SetLikeOnProject.as_view()),
    path("<int:project_pk>/news/", NewsList.as_view()),
    path("<int:project_pk>/news/<int:pk>/", NewsDetail.as_view()),
    path(
        "<int:project_pk>/news/<int:pk>/set_viewed/", ProjectNewsDetailSetViewed.as_view()
    ),
    path(
        "<int:project_pk>/news/<int:pk>/set_liked/", ProjectNewsDetailSetLiked.as_view()
    ),
    path("<int:pk>/collaborators/", ProjectCollaborators.as_view()),
    path("<int:pk>/", ProjectDetail.as_view()),
    path("<int:pk>/recommended_users", ProjectRecommendedUsers.as_view()),
    path("count/", ProjectCountView.as_view()),
    path("steps/", ProjectSteps.as_view()),
    path("achievements/", AchievementList.as_view()),
    path("achievements/<int:pk>/", AchievementDetail.as_view()),
    path("<int:pk>/responses/", ProjectVacancyResponses.as_view()),
]
