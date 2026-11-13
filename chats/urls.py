from django.urls import path

from chats.channel_views import (
    ProgramChannelDetail,
    ProgramChannelHistory,
    ProgramChannelList,
    ProgramChannelMessageChange,
    ProgramChannelReadView,
)
from chats.models import DirectChat, ProgramChannel, ProjectChat
from chats.serializers import (
    DirectChatMessageListSerializer,
    ProgramChannelMessageSerializer,
    ProjectChatMessageListSerializer,
)
from chats.views import (
    ChatAttachmentDownload,
    ChatMessageChanges,
    ChatMessageContext,
    ChatFileList,
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
    path("channels/", ProgramChannelList.as_view(), name="program-channel-list"),
    path(
        "channels/<int:id>/",
        ProgramChannelDetail.as_view(),
        name="program-channel-detail",
    ),
    path(
        "channels/<int:id>/messages/",
        ProgramChannelHistory.as_view(),
        name="program-channel-messages",
    ),
    path(
        "channels/<int:id>/read/",
        ProgramChannelReadView.as_view(),
        name="program-channel-read",
    ),
    path(
        "channels/<int:id>/messages/<int:message_id>/",
        ProgramChannelMessageChange.as_view(),
        name="program-channel-message-change",
    ),
    path(
        "channels/<int:id>/messages/changes/",
        ChatMessageChanges.as_view(
            chat_model=ProgramChannel, serializer_class=ProgramChannelMessageSerializer
        ),
        name="program-channel-message-changes",
    ),
    path(
        "channels/<int:id>/messages/<int:message_id>/context/",
        ChatMessageContext.as_view(
            chat_model=ProgramChannel, serializer_class=ProgramChannelMessageSerializer
        ),
        name="program-channel-message-context",
    ),
    path(
        "channels/<int:id>/files/",
        ChatFileList.as_view(chat_model=ProgramChannel),
        name="program-channel-files",
    ),
    path(
        "channels/<int:id>/messages/<int:message_id>/files/<slug:attachment_id>/download/",
        ChatAttachmentDownload.as_view(chat_model=ProgramChannel),
        name="program-channel-attachment-download",
    ),
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
        "directs/<slug:id>/messages/changes/",
        ChatMessageChanges.as_view(
            chat_model=DirectChat, serializer_class=DirectChatMessageListSerializer
        ),
        name="direct-chat-message-changes",
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
        "projects/<int:id>/messages/changes/",
        ChatMessageChanges.as_view(
            chat_model=ProjectChat, serializer_class=ProjectChatMessageListSerializer
        ),
        name="project-chat-message-changes",
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
