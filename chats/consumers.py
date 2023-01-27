from typing import Optional

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache

from chats.models import (
    BaseChat,
    DirectChat,
    DirectChatMessage,
    ProjectChat,
    ProjectChatMessage,
)
from chats.utils import clean_message_text, get_user_id_from_token, validate_message_text
from chats.websockets_settings import ChatType, Content, Event, EventType, Headers
from core.constants import ONE_DAY_IN_SECONDS
from projects.models import Project
from users.models import CustomUser


class ChatConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.room_name: str = ""
        self.user: Optional[CustomUser] = None
        self.chat_type = None
        self.chat: Optional[BaseChat] = None

    async def connect(self):
        # Join room group
        await self.accept()

    async def disconnect(self, close_code):
        pass
        # Leave room group
        #
        # # remove user from online cache
        # if self.chat:
        #     cache_key = self.__get_cache_key()
        #     current_online_list = cache.get(cache_key, [])
        #     current_online_list.remove(self.user.pk)
        #     cache.set(cache_key, current_online_list, ONE_DAY_IN_SECONDS)
        #
        # async_to_sync(self.channel_layer.group_discard)(self.room_name, self.channel_name)

    # Receive message from WebSocket
    async def receive_json(self, content, **kwargs):
        event = Event(
            type=content["type"],
            headers=Headers(content["headers"]),
            content=Content(**content["content"]),
        )
        token = event.headers.Authorization
        user_id = get_user_id_from_token(token)

        if event.type == EventType.NEW_MESSAGE:
            room_name = f"{EventType.NEW_MESSAGE}_{event.content.chat_id}"
        elif event.type == EventType.TYPING:
            room_name = f"{EventType.TYPING}_{event.content.chat_id}"
        elif event.type == EventType.READ_MESSAGE:
            room_name = f"{EventType.READ_MESSAGE}_{event.content.chat_id}"
        elif event.type == EventType.DELETE_MESSAGE:
            room_name = f"{EventType.DELETE_MESSAGE}_{event.content.chat_id}"
        elif event.type == EventType.SET_ONLINE:
            room_name = f"{EventType.SET_ONLINE}_{user_id}"
        elif event.type == EventType.SET_OFFLINE:
            room_name = f"{EventType.SET_OFFLINE}_{user_id}"
        else:
            return self.disconnect(400)

        if room_name.startswith(ChatType.DIRECT):
            if not self.__connect_to_direct_chat():
                return self.disconnect(400)
        elif room_name.startswith(ChatType.PROJECT):
            if not self.__connect_to_project_chat():
                return self.disconnect(400)

        if event.type == EventType.NEW_MESSAGE:
            await self.__process_new_message(content)
        elif event.type == EventType.TYPING:
            await self.__process_typing_event(content)
        elif event.type == EventType.READ_MESSAGE:
            await self.__process_read_event(content)

    async def __set_user_online(self):
        room_name = f"{EventType.SET_ONLINE}_{self.user.pk}"
        self.channel_layer.group_add(room_name, self.channel_name)

        cache_key = self.__get_cache_key()
        if self.chat_type == ChatType.DIRECT:
            current_online_list = cache.get(cache_key, [])
            current_online_list.append(self.user.pk)
            cache.set(cache_key, current_online_list, ONE_DAY_IN_SECONDS)
        elif self.chat_type == ChatType.PROJECT:
            current_online_list = cache.get(cache_key, [])
            current_online_list.append(self.user.pk)
            cache.set(cache_key, current_online_list, ONE_DAY_IN_SECONDS)
        else:
            raise ValueError("Chat type is not supported! Something went terribly wrong!")

    async def __process_connection_event(self):
        """

        Send connection event to everyone

        """

    async def __process_typing_event(self, content):
        """Send typing event to room group."""
        pass

    async def __process_read_event(self, content):
        """Send message read event to room group."""
        pass

    async def __process_new_message(self, content):
        """Send new message to everyone"""
        text = clean_message_text(content["text"])
        if not validate_message_text(text):
            return

        if self.chat_type == ChatType.DIRECT:
            DirectChatMessage.objects.create(chat=self.chat, author=self.user, text=text)
        elif self.chat_type == ChatType.PROJECT:
            ProjectChatMessage.objects.create(chat=self.chat, author=self.user, text=text)
        else:
            return

        self.channel_layer.group_send(
            self.room_name,
            {
                "type": "chat_message_echo",
                "name": content["name"],
                "message": text,
            },
        )

    async def __get_cache_key(self):
        return f"online_list_{self.chat_type}_{self.chat.pk}"

    async def __connect_to_direct_chat(self) -> bool:
        # room name looks like "direct_{other_user_id}"
        # room_name = self.scope["url_route"]["kwargs"]["room_name"]
        try:
            other_user_id = int(self.room_name.split("_")[1])
            other_user = CustomUser.objects.filter(id=other_user_id).first()
        except (IndexError, ValueError):
            # todo meaningful error message
            return False

        if not other_user or other_user_id == self.user.id:
            # such user does not exist / user tries to chat with himself
            await self.close()
            return False

        user1_id = min(self.user.pk, other_user_id)
        user2_id = max(self.user.pk, other_user_id)

        self.room_name = f"direct_{user1_id}_{user2_id}"
        self.chat_type = "direct"
        self.chat = DirectChat.objects.get_chat(self.user, other_user)
        return True

    async def __connect_to_project_chat(self) -> bool:
        # room name looks like "project_{project_id}"
        room_name = self.scope["url_route"]["kwargs"]["room_name"]
        project_id = int(room_name.split("_")[1])
        filtered_projects = Project.objects.filter(pk=project_id)

        if not filtered_projects.exists():
            # project does not exist
            await self.close()
            return False

        if not filtered_projects.first().collaborator_set.filter(user=self.user).exists():
            # user is not a collaborator
            await self.close()
            return False

        self.room_name = f"project_{project_id}"
        self.chat_type = "project"
        self.chat = ProjectChat.objects.get(project_id=project_id)
        return True


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    # # TODO: implement
    # def __init__(self, *args, **kwargs):
    #     super().__init__(args, kwargs)
    #     self.user = None

    async def connect(self):
        # self.user = self.scope["user"]
        # if not self.user.is_authenticated:
        #     return
        #
        # self.accept()
        pass
        # Send count of unread messages
