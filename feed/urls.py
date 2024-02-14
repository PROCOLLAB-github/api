from django.urls import path

from feed.views import FeedList

app_name = "feed"

urlpatterns = [
    path("", FeedList.as_view()),
]
