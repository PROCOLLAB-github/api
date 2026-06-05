from django.urls import path

from events.views import EventsList, EventDetail, EventRegisteredUsersList, EventTypes

app_name = "events"

# Файл сохранен для возможного возврата модуля мероприятий, но сейчас не
# подключен в `procollab/urls.py`, поэтому /events/ endpoints недоступны извне.
urlpatterns = [
    path("", EventsList.as_view()),
    path("<int:pk>/", EventDetail.as_view()),
    path("<int:id>/registered/", EventRegisteredUsersList.as_view()),
    path("types/", EventTypes.as_view()),
]
