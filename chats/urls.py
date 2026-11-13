from django.urls import path

from chats.models import DirectChat, ProjectChat
from chats.serializers import (
    DirectChatMessageListSerializer,
    ProjectChatMessageListSerializer,
)
from chats.views import (
    ChatAttachmentDownload,
    ChatMessageContext,
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
    path("directs/<slug:id>/", DirectChatDetail.as_view(), name="direct-chat-detail"),
    path(
        "directs/<slug:id>/messages/",
        DirectChatMessageList.as_view(),
        name="direct-chat-messages",
    ),
    path(
        "directs/<slug:id>/files/",
        DirectChatFileList.as_view(),
        name="direct-chat-files",
    ),
    path(
        "directs/<slug:id>/messages/<int:message_id>/context/",
        ChatMessageContext.as_view(
            chat_model=DirectChat, serializer_class=DirectChatMessageListSerializer
        ),
        name="direct-chat-message-context",
    ),
    path(
        "directs/<slug:id>/messages/<int:message_id>/files/<slug:attachment_id>/download/",
        ChatAttachmentDownload.as_view(chat_model=DirectChat),
        name="direct-chat-attachment-download",
    ),
    path("projects/", ProjectChatList.as_view(), name="project-chat-list"),
    path("projects/<int:pk>/", ProjectChatDetail.as_view(), name="project-chat-detail"),
    path(
        "projects/<int:id>/messages/",
        ProjectChatMessageList.as_view(),
        name="project-chat-messages",
    ),
    path(
        "projects/<int:id>/files/",
        ProjectChatFileList.as_view(),
        name="project-chat-files",
    ),
    path(
        "projects/<int:id>/messages/<int:message_id>/context/",
        ChatMessageContext.as_view(
            chat_model=ProjectChat, serializer_class=ProjectChatMessageListSerializer
        ),
        name="project-chat-message-context",
    ),
    path(
        "projects/<int:id>/messages/<int:message_id>/files/<slug:attachment_id>/download/",
        ChatAttachmentDownload.as_view(chat_model=ProjectChat),
        name="project-chat-attachment-download",
    ),
    path(
        "has-unreads/",
        HasChatUnreadsView.as_view(),
        name="has-chat-unreads",
    ),
]
