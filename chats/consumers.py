import json
from typing import Optional

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache

from chats.exceptions import NonMatchingDirectChatIdException
from chats.models import (
    BaseChat,
    DirectChatMessage,
    DirectChat,
)
from chats.utils import get_user_channel_cache_key
from chats.websockets_settings import (
    Content,
    Event,
    EventType,
    EventGroupType,
    ChatType,
)
from core.constants import ONE_DAY_IN_SECONDS, ONE_WEEK_IN_SECONDS
from core.utils import get_user_online_cache_key
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

        self.user = self.scope["user"]
        cache.set(
            get_user_channel_cache_key(self.user), self.channel_name, ONE_WEEK_IN_SECONDS
        )

        await self.channel_layer.group_add(
            EventGroupType.GENERAL_EVENTS, self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        """User disconnected from websocket, Don't have to do anything here"""
        pass

    async def receive_json(self, content, **kwargs):
        """Receive message from WebSocket in JSON format"""
        event = Event(
            type=content["type"],
            content=Content(
                **content.get(
                    "content", {"chat_id": None, "message": None, "chat_type": None}
                )
            ),
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

    async def __process_typing_event(self, content):
        """Send typing event to room group."""
        pass

    async def __process_read_event(self, content):
        """Send message read event to room group."""
        pass

    async def __process_chat_related_event(self, event, room_name):
        if event.type == EventType.NEW_MESSAGE:
            if event.content.chat_type == ChatType.DIRECT:
                # create new message
                chat_id = event.content.chat_id

                # todo add try/except
                user1_id, user2_id = map(int, chat_id.split("_"))
                if user1_id == self.user.id or user2_id == self.user.id:
                    other_user = await sync_to_async(CustomUser.objects.get)(
                        id=user1_id if user1_id != self.user.id else user2_id
                    )
                else:
                    raise NonMatchingDirectChatIdException

                # check if chat exists
                try:
                    await sync_to_async(DirectChat.objects.get)(pk=event.content.chat_id)
                except DirectChat.DoesNotExist:
                    # create a chat
                    print(self.user, other_user)
                    await sync_to_async(DirectChat.create_from_two_users)(
                        self.user, other_user
                    )

                msg = await sync_to_async(DirectChatMessage.objects.create)(
                    chat_id=event.content.chat_id,
                    sender=self.user,
                    message=event.content.message,
                )
                # send message to user's channel
                other_user_channel = cache.get(
                    get_user_channel_cache_key(other_user), None
                )
                if other_user_channel is None:
                    return

                await self.channel_layer.send(
                    other_user_channel,
                    {
                        "type": "chat_message",
                        "message": {
                            "id": msg.id,
                            "chat_id": msg.chat_id,
                            "author": msg.author,
                            "text": msg.message,
                            "created_at": msg.created_at,
                        },
                    },
                )

    async def chat_message(self, event):
        await self.send(json.dumps(event))

    async def set_online(self, event):
        await self.send(json.dumps(event))

    async def set_offline(self, event):
        await self.send(json.dumps(event))

    async def __process_general_event(self, event, room_name):
        cache_key = get_user_online_cache_key(self.user)
        if event.type == EventType.SET_ONLINE:
            cache.set(cache_key, True, ONE_DAY_IN_SECONDS)

            # sent everyone online event that user X is online
            await self.channel_layer.group_send(
                room_name, {"type": EventType.SET_ONLINE, "user_id": self.user.pk}
            )
        elif event.type == EventType.SET_OFFLINE:
            cache.delete(cache_key)

            # sent everyone online event that user X is offline
            await self.channel_layer.group_send(
                room_name, {"type": EventType.SET_OFFLINE, "user_id": self.user.pk}
            )
        else:
            raise ValueError("Unknown event type")


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    # TODO: implement this
    pass
