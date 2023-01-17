from django.urls import path

from chats.views import DirectChatList, DirectChatMessageList, ProjectChatList, ProjectChatMessageList

app_name = "chats"

urlpatterns = [
    path("direct-chats/", DirectChatList.as_view(), name="chat-list"),
    path("project-chats/", ProjectChatList.as_view(), name="chat-list"),
    path("direct-chat-messages/", DirectChatMessageList.as_view(), name="chat-list"),
    path("project-chat-messages/", ProjectChatMessageList.as_view(), name="chat-list"),
]
