from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from auth_jwt.views import RegisterUserView


urlpatterns = [
    path('register/', RegisterUserView.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
