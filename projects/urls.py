from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from projects.views import ProjectDetail, ProjectList

app_name = "projects"

urlpatterns = [
    path("", ProjectList.as_view()),
    path("<int:pk>/", ProjectDetail.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
