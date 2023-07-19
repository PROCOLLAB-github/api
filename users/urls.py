from django.urls import path, re_path

from users.views import (
    AchievementDetail,
    AchievementList,
    CurrentUser,
    EmailResetPassword,
    ResetPassword,
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
    path("users/<int:pk>/", UserDetail.as_view()),
    path("users/<int:pk>/set_onboarding_stage/", SetUserOnboardingStage.as_view()),
    path("users/reset-password/", EmailResetPassword.as_view()),
    path("users/current/", CurrentUser.as_view()),
    path("users/current/programs/", CurrentUserPrograms.as_view()),
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
    re_path(
        r"^password-reset/",
        ResetPassword.as_view(),
        name="password_reset_sent",
    ),
    re_path(
        r"^password-reset/(?P<key>[-:\w]+)/$",
        ResetPassword.as_view(),
        name="password_reset",
    ),
]
