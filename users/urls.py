from django.urls import path, re_path, include

from news.views import NewsList, NewsDetail, NewsDetailSetViewed, NewsDetailSetLiked
from users.views import (
    AchievementDetail,
    AchievementList,
    CurrentUser,
    SpecialistsList,
    UserAdditionalRolesView,
    UserDetail,
    UserProjectsList,
    UserList,
    UserTypesView,
    VerifyEmail,
    LogoutView,
    LikedProjectList,
    RegisteredEventsList,
    SetUserOnboardingStage,
    ResendVerifyEmail,
    CurrentUserPrograms,
    CurrentUserProgramsTags,
    ForceVerifyView,
    UserSubscribedProjectsList,
    UserSpecializationsNestedView,
    UserSpecializationsInlineView,
    SingleUserDataView,
)

app_name = "users"

urlpatterns = [
    path(
        "specialists/", SpecialistsList.as_view()
    ),  # this url actually returns  mentors, experts and investors
    path("users/", UserList.as_view()),
    path("users/projects/", UserProjectsList.as_view()),
    path("users/liked/", LikedProjectList.as_view()),
    path("users/roles/", UserAdditionalRolesView.as_view()),
    path("users/types/", UserTypesView.as_view()),
    path("users/specializations/nested/", UserSpecializationsNestedView.as_view()),
    path("users/specializations/inline/", UserSpecializationsInlineView.as_view()),
    path("users/<int:pk>/", UserDetail.as_view()),
    path("users/<int:pk>/subscribed_projects/", UserSubscribedProjectsList.as_view()),
    path("users/<int:pk>/set_onboarding_stage/", SetUserOnboardingStage.as_view()),
    path("users/<int:pk>/force_verify/", ForceVerifyView.as_view()),
    path("users/<int:user_pk>/news/", NewsList.as_view()),
    path("users/<int:user_pk>/news/<int:pk>/", NewsDetail.as_view()),
    path("users/<int:user_pk>/news/<int:pk>/set_viewed/", NewsDetailSetViewed.as_view()),
    path("users/<int:user_pk>/news/<int:pk>/set_liked/", NewsDetailSetLiked.as_view()),
    path("users/current/", CurrentUser.as_view()),
    # todo: change password view
    path("users/current/programs/", CurrentUserPrograms.as_view()),
    path("users/current/programs/tags/", CurrentUserProgramsTags.as_view()),
    path("users/current/events/", RegisteredEventsList.as_view()),
    path("users/achievements/", AchievementList.as_view()),
    path("users/achievements/<int:pk>/", AchievementDetail.as_view()),
    path("logout/", LogoutView.as_view()),
    path(
        "resend_email/",
        ResendVerifyEmail.as_view(),
        name="account_email_verification_resent",
    ),
    re_path(
        r"^account-confirm-email/",
        VerifyEmail.as_view(),
        name="account_email_verification_sent",
    ),
    re_path(
        r"^account-confirm-email/(?P<key>[-:\w]+)/$",
        VerifyEmail.as_view(),
        name="account_confirm_email",
    ),
    path(
        "reset_password/",
        include("django_rest_passwordreset.urls", namespace="password_reset"),
    ),
    # for skills
    path("users/clone-data", SingleUserDataView.as_view()),
]
