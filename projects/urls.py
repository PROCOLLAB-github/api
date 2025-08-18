from django.urls import path

from news.views import NewsDetail, NewsDetailSetLiked, NewsDetailSetViewed, NewsList
from partner_programs.views import PartnerProgramFieldValueBulkUpdateView
from projects.views import (
    AchievementDetail,
    AchievementList,
    DuplicateProjectView,
    LeaveProject,
    ProjectCollaborators,
    ProjectCountView,
    ProjectDetail,
    ProjectList,
    ProjectRecommendedUsers,
    ProjectSteps,
    ProjectSubscribe,
    ProjectSubscribers,
    ProjectUnsubscribe,
    ProjectVacancyResponses,
    SetLikeOnProject,
    SwitchLeaderRole,
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
    path("<int:project_pk>/collaborators/leave/", LeaveProject.as_view()),
    path(
        "<int:project_pk>/collaborators/<int:user_to_leader_pk>/switch-leader/",
        SwitchLeaderRole.as_view(),
    ),
    path("<int:pk>/", ProjectDetail.as_view()),
    path("<int:pk>/recommended_users", ProjectRecommendedUsers.as_view()),
    path(
        "assign-to-program/", DuplicateProjectView.as_view(), name="duplicate-project"
    ),
    path(
        "<int:project_id>/program-fields/",
        PartnerProgramFieldValueBulkUpdateView.as_view(),
        name="update_program_fields",
    ),
    path("count/", ProjectCountView.as_view()),
    path("steps/", ProjectSteps.as_view()),
    path("achievements/", AchievementList.as_view()),
    path("achievements/<int:pk>/", AchievementDetail.as_view()),
    path("<int:id>/responses/", ProjectVacancyResponses.as_view()),
]
