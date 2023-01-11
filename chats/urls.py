from django.urls import path

from chats.views import ChatList

app_name = "chats"

urlpatterns = [
    path("my/", ChatList.as_view()),
]
