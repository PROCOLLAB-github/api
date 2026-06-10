from django.urls import path

from feed.views import NewSimpleFeed

app_name = "feed"

urlpatterns = [
    path("", NewSimpleFeed.as_view()),
]
