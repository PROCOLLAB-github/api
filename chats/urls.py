from django.urls import path

from chats.views import (
    DirectChatList,
    DirectChatMessageList,
    ProjectChatList,
    ProjectChatMessageList,
    ProjectChatDetail,
)

app_name = "chats"

urlpatterns = [
    path("direct_chats/", DirectChatList.as_view(), name="direct-chat-list"),
    path("project_chats/", ProjectChatList.as_view(), name="project-chat-list"),
    path(
        "project_chats/<int:pk>/", ProjectChatDetail.as_view(), name="project-chat-detail"
    ),
    path(
        "direct_chat_messages/",
        DirectChatMessageList.as_view(),
        name="direct-chat-messages",
    ),
    path(
        "project_chat_messages/",
        ProjectChatMessageList.as_view(),
        name="project-chat-messages",
    ),
]
