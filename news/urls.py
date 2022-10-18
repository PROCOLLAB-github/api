from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from news.views import NewsDetail, NewsList

app_name = "news"

urlpatterns = [
    path("", NewsList.as_view()),
    path("<int:pk>/", NewsDetail.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
