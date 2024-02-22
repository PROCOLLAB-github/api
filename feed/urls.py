from django.urls import path

from feed.views import NewSimpleFeed, DevScript

app_name = "feed"

urlpatterns = [
    path("", NewSimpleFeed.as_view()),
    path("dev-needs-script", DevScript.as_view()),
]
