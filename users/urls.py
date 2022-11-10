from django.urls import path, re_path

from users.views import (
    EmailResetPassword,
    ResetPassword,
    SpecialistsList,
    UserAdditionalRolesView,
    UserDetail,
    UserList,
    UserTypesView,
    VerifyEmail,
)

app_name = "users"

urlpatterns = [
    path(
        "specialists/", SpecialistsList.as_view()
    ),  # this url actually returns  mentors, experts and investors
    path("users/", UserList.as_view()),
    path("users/roles/", UserAdditionalRolesView.as_view()),
    path("users/types/", UserTypesView.as_view()),
    path("users/<int:pk>/", UserDetail.as_view()),
    path("users/reset-password/", EmailResetPassword.as_view()),
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
