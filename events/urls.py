from django.urls import path

from events.views import EventsList, EventDetail, EventRegisteredUsersList

app_name = "events"

urlpatterns = [
    path("", EventsList.as_view()),
    path("<int:pk>/", EventDetail.as_view()),
    path("<int:pk>/registered/", EventRegisteredUsersList.as_view()),
]
