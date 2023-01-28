from typing import Optional

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache

from chats.models import (
    BaseChat,
)
from chats.websockets_settings import (
    Content,
    Event,
    EventType,
    Headers,
    EventGroupType,
    ONLINE_USER_CACHE_KEY_PREFIX,
)
from core.constants import ONE_DAY_IN_SECONDS
from users.models import CustomUser


class ChatConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.room_name: str = ""
        self.user: Optional[CustomUser] = None
        self.chat_type = None
        self.chat: Optional[BaseChat] = None

    async def connect(self):
        """User connected to websocket"""

        if self.scope["user"].is_anonymous:
            return await self.close(403)

        await self.accept()
        await self.channel_layer.group_add(
            EventGroupType.GENERAL_EVENTS, self.channel_name
        )

    async def disconnect(self, close_code):
        """User disconnected from websocket, Don't have to do anything here"""
        pass

    async def receive_json(self, content, **kwargs):
        """Receive message from WebSocket in JSON format"""
        event = Event(
            type=content["type"],
            headers=Headers(content["headers"]),
            content=Content(**content["content"]),
        )

        # two event types - related to group chat and related to leave/connect
        if event.type in [
            EventType.NEW_MESSAGE,
            EventType.TYPING,
            EventType.READ_MESSAGE,
            EventType.DELETE_MESSAGE,
        ]:
            room_name = f"{EventGroupType.CHATS_RELATED}_{event.content.chat_id}"
            await self.__process_chat_related_event(event, room_name)
        elif event.type in [EventType.SET_ONLINE, EventType.SET_OFFLINE]:
            room_name = EventGroupType.GENERAL_EVENTS
            await self.__process_general_event(event, room_name)
        else:
            return self.disconnect(400)

    async def __process_connection_event(self):
        """Send connection event to everyone"""

    async def __process_typing_event(self, content):
        """Send typing event to room group."""
        pass

    async def __process_read_event(self, content):
        """Send message read event to room group."""
        pass

    async def __process_chat_related_event(self, event, room_name):
        pass

    async def __process_general_event(self, event, room_name):
        cache_key = f"{ONLINE_USER_CACHE_KEY_PREFIX}{self.user.pk}"
        if event.type == EventType.SET_ONLINE:
            cache.set(cache_key, True, ONE_DAY_IN_SECONDS)

            # sent everyone online event that user X is online
            self.channel_layer.group_send(
                room_name, {"type": EventType.SET_ONLINE, "user_id": self.user.pk}
            )
        elif event.type == EventType.SET_OFFLINE:
            cache.delete(cache_key)

            # sent everyone online event that user X is offline
            self.channel_layer.group_send(
                room_name, {"type": EventType.SET_OFFLINE, "user_id": self.user.pk}
            )
        else:
            raise ValueError("Unknown event type")


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
