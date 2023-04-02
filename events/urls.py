from django.urls import path

from events.views import EventsList, EventDetail, EventRegisteredUsersList

app_name = "events"

urlpatterns = [
    path("", EventsList.as_view()),
    path("<int:pk>/", EventDetail.as_view()),
    path("registered/<int:pk>/", EventRegisteredUsersList.as_view()),
]
