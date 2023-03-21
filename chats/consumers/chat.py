import datetime
import json
from typing import Optional

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache
from django.utils import timezone

from chats.exceptions import ChatException
from chats.models import BaseChat
from chats.utils import get_user_channel_cache_key
from chats.websockets_settings import (
    Event,
    EventType,
    EventGroupType,
    ChatType,
)
from core.constants import ONE_DAY_IN_SECONDS, ONE_WEEK_IN_SECONDS
from core.utils import get_user_online_cache_key
from projects.models import Collaborator
from users.models import CustomUser
from chats.consumers.event_types import DirectEvent, ProjectEvent


class ChatConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.room_name: str = ""
        self.user: Optional[CustomUser] = None
        self.chat_type = None
        self.chat: Optional[BaseChat] = None
        self.event = None

    async def connect(self):
        """User connected to websocket"""

        if self.scope["user"].is_anonymous:
            # not authenticated
            return await self.close(403)

        self.user = self.scope["user"]
        cache.set(
            get_user_channel_cache_key(self.user), self.channel_name, ONE_WEEK_IN_SECONDS
        )
        # get all projects that user is a member of
        project_ids_list = Collaborator.objects.filter(user=self.user).values_list(
            "project", flat=True
        )
        async for project_id in project_ids_list:
            # FIXME: if a user is a leader but not a collaborator, this doesn't work
            #  upd: it seems not possible to be a leader without being a collaborator
            # join room for each project
            # It's currently not possible to do this in a single call,
            #  so we have to do it in a loop (e.g. that's O(N) calls to layer backend, redis cache that would be)
            await self.channel_layer.group_add(
                f"{EventGroupType.CHATS_RELATED}_{project_id}", self.channel_name
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

        # todo reply_to key is not required
        event = Event(type=content["type"], content=content.get("content"))

        # two event types - related to group chat and related to leave/connect
        if event.type in [
            EventType.NEW_MESSAGE,
            EventType.TYPING,
            EventType.READ_MESSAGE,
            EventType.DELETE_MESSAGE,
            EventType.EDIT_MESSAGE,
        ]:

            if event.content["chat_type"] == ChatType.DIRECT:
                self.event = DirectEvent(self.user, self.channel_layer, self.channel_name)
            elif event.content["chat_type"] == ChatType.PROJECT:
                self.event = ProjectEvent(
                    self.user, self.channel_layer, self.channel_name
                )

            room_name = f"{EventGroupType.CHATS_RELATED}_{event.content.get('chat_id')}"
            try:
                await self.__process_chat_related_event(event, room_name)
            except ChatException as e:
                await self.send_json({"error": str(e.get_error())})
            except KeyError as e:
                await self.send_json(
                    {
                        "error": f"Missing key (might be backend's fault,"
                        f" but most likely you are missing this field): {e}"
                    }
                )

        elif event.type in [EventType.SET_ONLINE, EventType.SET_OFFLINE]:
            room_name = EventGroupType.GENERAL_EVENTS
            await self.__process_general_event(event, room_name)
        else:
            return self.disconnect(400)

    async def __process_chat_related_event(self, event, room_name):
        if event.type == EventType.NEW_MESSAGE:
            await self.event.process_new_message_event(event, room_name)
        elif event.type == EventType.TYPING:
            await self.event.process_typing_event(event, room_name)
        elif event.type == EventType.READ_MESSAGE:
            await self.event.process_read_message_event(event, room_name)
        elif event.type == EventType.DELETE_MESSAGE:
            await self.event.process_delete_message_event(event, room_name)
        elif event.type == EventType.EDIT_MESSAGE:
            await self.event.process_edit_message_event(event, room_name)

    async def __process_typing_event(self, event: Event, room_name: str):
        """Send typing event to room group."""
        event_data = {
            "type": EventType.TYPING,
            "content": {
                "chat_id": event.content["chat_id"],
                "chat_type": event.content["chat_type"],
                "user_id": self.user.id,
                "end_time": (timezone.now() + datetime.timedelta(seconds=5)).isoformat(),
            },
        }

        if event.content["chat_type"] == ChatType.DIRECT:
            # fixme: need to move this to func
            chat_id, other_user = await get_chat_and_user_ids_from_content(
                event.content, self.user
            )

            # if chat_id == 17_7, then chat_id will be == 7_17
            chat_id = DirectChat.get_chat_id_from_users(self.user, other_user)

            # check if chat exists
            try:
                await sync_to_async(DirectChat.objects.get)(pk=chat_id)
            except DirectChat.DoesNotExist:
                # if not, create such chat
                await sync_to_async(DirectChat.create_from_two_users)(
                    self.user, other_user
                )

            # send message to user's channel
            other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)

            if other_user_channel:
                await self.channel_layer.send(other_user_channel, event_data)

        await self.channel_layer.group_send(
            room_name,
            event_data,
        )

    async def message_read(self, event: Event):
        await self.send(json.dumps(event))

    async def user_typing(self, event: Event):
        await self.send(json.dumps(event))

    async def new_message(self, event: Event):
        await self.send(json.dumps(event))

    async def delete_message(self, event: Event):
        await self.send(json.dumps(event))

    async def set_online(self, event: Event):
        await self.send(json.dumps(event))

    async def set_offline(self, event: Event):
        await self.send(json.dumps(event))

    async def edit_message(self, event: Event):
        await self.send(json.dumps(event))

    async def __process_general_event(self, event: Event, room_name: str):
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

            # TODO: close connection here?
            # await self.close(200)
        else:
            raise ValueError("Unknown event type")


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    # TODO: implement this
    pass
