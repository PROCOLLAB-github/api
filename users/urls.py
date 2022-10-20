from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from users.views import UserDetail, UserList

app_name = "users"

urlpatterns = [
    path("users/", UserList.as_view()),
    path("users/<int:pk>/", UserDetail.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
