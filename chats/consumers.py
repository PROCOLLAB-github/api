from typing import Optional

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer
from django.core.cache import cache

from chats.models import (
    DirectChat,
    DirectChatMessage,
    ProjectChat,
    ProjectChatMessage,
    BaseChat,
)
from chats.utils import clean_message_text, validate_message_text
from chats.websockets_settings import ChatType, EventType
from core.constants import ONE_DAY_IN_SECONDS
from projects.models import Project
from users.models import CustomUser


class ChatConsumer(JsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.room_name: str = None
        self.user: Optional[CustomUser] = None
        self.chat_type = None
        self.chat: Optional[BaseChat] = None

    def connect(self):
        # Join room group
        # authentication
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            return

        room_name = self.scope["url_route"]["kwargs"]["room_name"]
        if room_name.startswith(ChatType.DIRECT.value):
            if not self.__connect_to_direct_chat():
                return
        elif room_name.startswith(ChatType.PROJECT.value):
            if not self.__connect_to_project_chat():
                return
        # ugly way to paginate messages
        # messages = self.chat.get_last_messages(30)  # TODO: set 30 as a constant somewhere
        # has_more_messages = self.chat.messages.all().count() > 30
        self.accept()

        cache_key = self.__get_cache_key()
        if self.chat_type == ChatType.DIRECT.value:
            current_online_list = cache.get(cache_key, [])
            current_online_list.append(self.user.pk)
            cache.set(cache_key, current_online_list, ONE_DAY_IN_SECONDS)
        elif self.chat_type == ChatType.PROJECT.value:
            current_online_list = cache.get(cache_key, [])
            current_online_list.append(self.user.pk)
            cache.set(cache_key, current_online_list, ONE_DAY_IN_SECONDS)
        else:
            raise ValueError("Chat type is not supported! Something went terribly wrong!")

        self.send_json(
            {
                "type": EventType.LAST_30_MESSAGES.value,
                "online_users": current_online_list,
            }
        )

        async_to_sync(self.channel_layer.group_add)(self.room_name, self.channel_name)

    def disconnect(self, close_code):
        # Leave room group

        # remove user from online cache
        cache_key = self.__get_cache_key()
        current_online_list = cache.get(cache_key, [])
        current_online_list.remove(self.user.pk)
        cache.set(cache_key, current_online_list, ONE_DAY_IN_SECONDS)

        async_to_sync(self.channel_layer.group_discard)(self.room_name, self.channel_name)

    # Receive message from WebSocket
    def receive_json(self, content, **kwargs):
        message_type = content["type"]

        if message_type == EventType.CHAT_MESSAGE.value:
            self.__process_new_message(content)
        elif message_type == EventType.TYPING.value:
            self.__process_typing_event(content)
        elif message_type == EventType.READ.value:
            self.__process_read_event(content)

    def __process_typing_event(self, content):
        """Send typing event to room group."""
        pass

    def __process_read_event(self, content):
        """Send message read event to room group."""
        pass

    def __process_new_message(self, content):
        """Send new message to everyone"""
        text = clean_message_text(content["text"])
        if not validate_message_text(text):
            return

        if self.chat_type == ChatType.DIRECT.value:
            DirectChatMessage.objects.create(chat=self.chat, author=self.user, text=text)
        elif self.chat_type == ChatType.PROJECT.value:
            ProjectChatMessage.objects.create(chat=self.chat, author=self.user, text=text)
        else:
            return

        async_to_sync(self.channel_layer.group_send)(
            self.room_name,
            {
                "type": "chat_message_echo",
                "name": content["name"],
                "message": text,
            },
        )

    def __get_cache_key(self):
        return f"online_list_{self.chat_type}_{self.chat.pk}"

    def __connect_to_direct_chat(self) -> bool:
        # room name looks like "direct_{other_user_id}"
        room_name = self.scope["url_route"]["kwargs"]["room_name"]
        other_user_id = int(room_name.split("_")[1])
        other_user = CustomUser.objects.filter(id=other_user_id).first()

        if not other_user or other_user_id == self.user.id:
            # such user does not exist / user tries to chat with himself
            self.close()
            return False

        user1_id = min(self.user.pk, other_user_id)
        user2_id = max(self.user.pk, other_user_id)

        self.room_name = f"direct_{user1_id}_{user2_id}"
        self.chat_type = "direct"
        self.chat = DirectChat.objects.get_chat(self.user, other_user)
        return True

    def __connect_to_project_chat(self) -> bool:
        # room name looks like "project_{project_id}"
        room_name = self.scope["url_route"]["kwargs"]["room_name"]
        project_id = int(room_name.split("_")[1])
        filtered_projects = Project.objects.filter(id=project_id)

        if not filtered_projects.exists():
            # project does not exist
            self.close()
            return False

        if not filtered_projects.first().collaborator_set.filter(user=self.user).exists():
            # user is not a collaborator
            self.close()
            return False

        self.room_name = f"project_{project_id}"
        self.chat_type = "project"
        self.chat = ProjectChat.objects.get(project_id=project_id)
        return True


class NotificationConsumer(JsonWebsocketConsumer):
    # TODO: implement
    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.user = None

    def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            return

        self.accept()

        # Send count of unread messages
