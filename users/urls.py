from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from users.views import UserDetail, UserList, EmailResetPassword

app_name = "users"

urlpatterns = [
    path("users/", UserList.as_view()),
    path("users/<int:pk>/", UserDetail.as_view()),
    path("users/reset-password/", EmailResetPassword.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
