from django.urls import path

from chats.views import (
    DirectChatList,
    DirectChatMessageList,
    ProjectChatList,
    ProjectChatMessageList,
    ProjectChatDetail,
    DirectChatDetail,
    # ChatAttachmentView,
)

app_name = "chats"

urlpatterns = [
    path("directs/", DirectChatList.as_view(), name="direct-chat-list"),
    # path("attachments/", ChatAttachmentView.as_view(), name="chat-attachments"),
    path("directs/<slug:pk>/", DirectChatDetail.as_view(), name="direct-chat-detail"),
    path("projects/", ProjectChatList.as_view(), name="project-chat-list"),
    path("projects/<int:pk>/", ProjectChatDetail.as_view(), name="project-chat-detail"),
    path(
        "directs/<slug:pk>/messages/",
        DirectChatMessageList.as_view(),
        name="direct-chat-messages",
    ),
    path(
        "projects/<int:pk>/messages/",
        ProjectChatMessageList.as_view(),
        name="project-chat-messages",
    ),
]
