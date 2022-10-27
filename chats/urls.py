from django.urls import path

from chats.views import ChatList, ChatDetail, MessageList, MessageDetail

app_name = "chats"

urlpatterns = [
    path("", ChatList.as_view()),
    path("<int:pk>/", ChatDetail.as_view()),
    path("<int:pk>/messages/", MessageList.as_view()),
    path("<int:pk>/messages/<int:message_id>/", MessageDetail.as_view()),
]
