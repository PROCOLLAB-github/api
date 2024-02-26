from django.urls import path

from news.views import NewsList, NewsDetail, NewsDetailSetLiked, NewsDetailSetViewed
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
    ProjectSubscribe,
    ProjectUnsubscribe,
    ProjectSubscribers,
)

app_name = "projects"

urlpatterns = [
    path("", ProjectList.as_view()),
    path("<int:pk>/like/", SetLikeOnProject.as_view()),
    path("<int:project_pk>/news/", NewsList.as_view()),
    path("<int:project_pk>/subscribe/", ProjectSubscribe.as_view()),
    path("<int:project_pk>/unsubscribe/", ProjectUnsubscribe.as_view()),
    path("<int:project_pk>/subscribers/", ProjectSubscribers.as_view()),
    path("<int:project_pk>/news/<int:pk>/", NewsDetail.as_view()),
    path("<int:project_pk>/news/<int:pk>/set_viewed/", NewsDetailSetViewed.as_view()),
    path("<int:project_pk>/news/<int:pk>/set_liked/", NewsDetailSetLiked.as_view()),
    path("<int:pk>/collaborators/", ProjectCollaborators.as_view()),
    path("<int:pk>/", ProjectDetail.as_view()),
    path("<int:pk>/recommended_users", ProjectRecommendedUsers.as_view()),
    path("count/", ProjectCountView.as_view()),
    path("steps/", ProjectSteps.as_view()),
    path("achievements/", AchievementList.as_view()),
    path("achievements/<int:pk>/", AchievementDetail.as_view()),
    path("<int:id>/responses/", ProjectVacancyResponses.as_view()),
]
