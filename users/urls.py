from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from users.views import UserRegisterAPI, UserUpdateDeleteAPI


urlpatterns = [
    path('register/', UserRegisterAPI.as_view()),
    path('update/<int:pk>', UserUpdateDeleteAPI.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
