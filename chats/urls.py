from django.urls import path

from chats.views import (
    DirectChatList,
    DirectChatMessageList,
    HasChatUnreadsView,
    ProjectChatList,
    ProjectChatMessageList,
    ProjectChatDetail,
    DirectChatDetail,
    ProjectChatFileList,
    DirectChatFileList,
)

app_name = "chats"

urlpatterns = [
    path("directs/", DirectChatList.as_view(), name="direct-chat-list"),
    path("directs/<slug:pk>/", DirectChatDetail.as_view(), name="direct-chat-detail"),
    path(
        "directs/<slug:pk>/messages/",
        DirectChatMessageList.as_view(),
        name="direct-chat-messages",
    ),
    path(
        "directs/<slug:pk>/files/",
        DirectChatFileList.as_view(),
        name="direct-chat-files",
    ),
    path("projects/", ProjectChatList.as_view(), name="project-chat-list"),
    path("projects/<int:pk>/", ProjectChatDetail.as_view(), name="project-chat-detail"),
    path(
        "projects/<int:pk>/messages/",
        ProjectChatMessageList.as_view(),
        name="project-chat-messages",
    ),
    path(
        "projects/<int:pk>/files/",
        ProjectChatFileList.as_view(),
        name="project-chat-files",
    ),
    path(
        "has-unreads/",
        HasChatUnreadsView.as_view(),
        name="has-chat-unreads",
    ),
]
