import datetime
import json
from typing import Optional

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache
from django.utils import timezone

from chats.exceptions import (
    WrongChatIdException,
    ChatException,
    UserNotInChatException,
)
from chats.models import (
    BaseChat,
    DirectChatMessage,
    DirectChat,
    ProjectChat,
    ProjectChatMessage,
)
from chats.utils import (
    get_user_channel_cache_key,
    create_message,
    get_chat_and_user_ids_from_content,
)
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
            room_name = f"{EventGroupType.CHATS_RELATED}_{event.content.get('chat_id')}"
            try:
                await self.__process_chat_related_event(event, room_name)
            except ChatException as e:
                await self.send_json({"error": str(e.get_error())})

        elif event.type in [EventType.SET_ONLINE, EventType.SET_OFFLINE]:
            room_name = EventGroupType.GENERAL_EVENTS
            await self.__process_general_event(event, room_name)
        else:
            return self.disconnect(400)

    async def __process_chat_related_event(self, event, room_name):
        if event.type == EventType.NEW_MESSAGE:
            await self.__process_new_message_event(event, room_name)
        elif event.type == EventType.TYPING:
            await self.__process_typing_event(event, room_name)
        elif event.type == EventType.READ_MESSAGE:
            await self.__process_read_message_event(event, room_name)
        elif event.type == EventType.DELETE_MESSAGE:
            await self.__process_delete_message_event(event, room_name)
        elif event.type == EventType.EDIT_MESSAGE:
            await self.__process_edit_message_event(event, room_name)

    async def __process_new_message_event(self, event, room_name):
        if event.content["chat_type"] == ChatType.DIRECT:
            await self.__process_new_direct_message_event(event)
        elif event.content["chat_type"] == ChatType.PROJECT:
            await self.__process_new_project_message_event(event, room_name)
        else:
            raise ValueError("Chat type is not supported")

    async def __process_new_direct_message_event(self, event: Event):
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
            await sync_to_async(DirectChat.create_from_two_users)(self.user, other_user)

        msg = await create_message(
            chat_id=chat_id,
            chat_model=DirectChatMessage,
            author=self.user,
            text=event.content["message"],
            reply_to=event.content["reply_to"],
        )

        content = {
            "type": EventType.NEW_MESSAGE,
            "content": {
                "message_id": msg.id,
                "chat_id": msg.chat_id,
                "chat_type": ChatType.PROJECT,
                "author_id": msg.author.pk,
                "text": msg.text,
                "created_at": msg.created_at.timestamp(),
                "is_edited": msg.is_edited,
            },
        }
        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)
        await self.channel_layer.send(self.channel_name, content)

        if other_user_channel is None:
            return

        await self.channel_layer.send(other_user_channel, content)

    async def __process_new_project_message_event(self, event: Event, room_name: str):
        chat_id = event.content["chat_id"]
        chat = await sync_to_async(ProjectChat.objects.get)(pk=chat_id)

        # check that user is in this chat
        users = await sync_to_async(chat.get_users)()
        if self.user not in users:
            raise UserNotInChatException(
                f"User {self.user.id} is not in project chat {chat_id}"
            )

        msg = await create_message(
            chat_id=chat_id,
            chat_model=ProjectChatMessage,
            author=self.user,
            text=event.content["message"],
            reply_to=event.content["reply_to"],
        )

        await self.channel_layer.group_send(
            room_name,
            {
                "type": EventType.NEW_MESSAGE,
                "content": {
                    "message_id": msg.id,
                    "chat_id": msg.chat_id,
                    "chat_type": ChatType.PROJECT,
                    "author_id": msg.author.pk,
                    "text": msg.text,
                    "created_at": msg.created_at.timestamp(),
                    "is_edited": msg.is_edited,
                },
            },
        )

    async def __process_typing_event(self, event: Event, room_name: str):
        """Send typing event to room group."""
        await self.channel_layer.group_send(
            room_name,
            {
                "type": EventType.TYPING,
                "content": {
                    "chat_id": event.content["chat_id"],
                    "chat_type": event.content["chat_type"],
                    "user_id": self.user.id,
                    "end_time": (
                        timezone.now() + datetime.timedelta(seconds=5)
                    ).timestamp(),
                },
            },
        )

    async def __process_read_message_event(self, event: Event, room_name: str):
        """Send message read event to room group."""
        if event.content["chat_type"] == ChatType.DIRECT:
            chat_id, other_user = await get_chat_and_user_ids_from_content(
                event.content, self.user
            )
            msg = await sync_to_async(DirectChatMessage.objects.get)(
                pk=event.content["message_id"]
            )
            if msg.chat_id != chat_id or msg.author_id != other_user:
                raise WrongChatIdException(
                    "Some of chat/message ids are wrong, you can't access this message"
                )
            msg.is_read = True
            await sync_to_async(msg.save)()
            # send 2 events to user's channel
            other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)
            json_thingy = {
                "type": EventType.READ_MESSAGE,
                "content": {
                    "chat_id": event.content["chat_id"],
                    "chat_type": event.content["chat_type"],
                    "user_id": self.user.id,
                    "message_id": event.content["message_id"],
                },
            }
            await self.channel_layer.send(self.channel_name, json_thingy)
            if other_user_channel is None:
                return
            await self.channel_layer.send(other_user_channel, json_thingy)
        elif event.content["chat_type"] == ChatType.PROJECT:
            msg = await sync_to_async(ProjectChatMessage.objects.get)(
                pk=event.content["message_id"]
            )
            chat = await sync_to_async(ProjectChat.objects.get)(pk=msg.chat_id)
            # check that user is in this chat
            users = await sync_to_async(chat.get_users)()
            if self.user not in users:
                raise UserNotInChatException(
                    f"User {self.user.id} is not in project chat {msg.chat_id}"
                )
            if msg.chat_id != event.content["chat_id"]:
                raise WrongChatIdException(
                    "Some of chat/message ids are wrong, you can't access this message"
                )
            msg.is_read = True
            await sync_to_async(msg.save)()
            await self.channel_layer.group_send(
                room_name,
                {
                    "type": EventType.READ_MESSAGE,
                    "content": {
                        "chat_id": event.content["chat_id"],
                        "chat_type": event.content["chat_type"],
                        "user_id": self.user.id,
                        "message_id": event.content["message_id"],
                    },
                },
            )

    async def __process_delete_message_event(self, event: Event, room_name: str):
        if event.content["chat_type"] == ChatType.DIRECT:
            await self.__process_delete_direct_message_event(event)
        elif event.content["chat_type"] == ChatType.PROJECT:
            await self.__process_delete_project_message_event(event, room_name)

    async def __process_edit_message_event(self, event, room_name):
        if event.content["chat_type"] == ChatType.DIRECT:
            await self.__process_edit_direct_message_event(event)
        elif event.content["chat_type"] == ChatType.PROJECT:
            await self.__process_edit_project_message_event(event, room_name)

    async def __process_delete_direct_message_event(self, event):
        message_id = event.content["message_id"]

        message = await sync_to_async(DirectChatMessage.objects.get)(pk=message_id)
        message.is_deleted = True
        await sync_to_async(message.save)()

        chat_id, other_user = await get_chat_and_user_ids_from_content(
            event.content, self.user
        )

        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)
        content = {
            "type": EventType.DELETE_MESSAGE,
            "content": {
                "message_id": message_id,
            },
        }
        await self.channel_layer.send(self.channel_name, content)

        if other_user_channel is None:
            return

        await self.channel_layer.send(other_user_channel, content)

    async def __process_delete_project_message_event(self, event: Event, room_name: str):
        chat_id = event.content["chat_id"]
        chat = await sync_to_async(ProjectChat.objects.get)(pk=chat_id)

        # check that user is in this chat
        users = await sync_to_async(chat.get_users)()
        if self.user not in users:
            raise UserNotInChatException(
                f"User {self.user.id} is not in project chat {chat_id}"
            )

        message = await sync_to_async(ProjectChatMessage.objects.get)(
            pk=event.content["message_id"]
        )
        message.is_deleted = True
        await sync_to_async(message.save)()

        await self.channel_layer.group_send(
            room_name,
            {
                "type": EventType.NEW_MESSAGE,
                "content": {"message_id": event.content["message_id"]},
            },
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

    async def __process_edit_direct_message_event(self, event):
        chat_id, other_user = await get_chat_and_user_ids_from_content(
            event.content, self.user
        )
        # if chat_id == 17_7, then chat_id will be == 7_17
        chat_id = DirectChat.get_chat_id_from_users(self.user, other_user)

        # check if chat exists ( this raises exception if not )
        await sync_to_async(DirectChat.objects.get)(pk=chat_id)

        msg = await sync_to_async(DirectChatMessage.objects.get)(
            pk=event.content["message_id"]
        )
        msg.text = event.content["message"]
        msg.is_edited = True
        await sync_to_async(msg.save)()
        content = {
            "type": EventType.EDIT_MESSAGE,
            "content": {
                "message_id": msg.id,
                "chat_id": msg.chat_id,
                "author_id": msg.author_id,
                "text": msg.text,
                "created_at": msg.created_at.timestamp(),
                "is_edited": msg.is_edited,
            },
        }
        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)
        await self.channel_layer.send(self.channel_name, content)

        if other_user_channel is None:
            return

        await self.channel_layer.send(other_user_channel, content)

    async def __process_edit_project_message_event(self, event, room_name):
        chat_id = event.content["chat_id"]
        chat = await sync_to_async(ProjectChat.objects.get)(pk=chat_id)

        # check that user is in this chat
        users = await sync_to_async(chat.get_users)()
        if self.user not in users:
            raise UserNotInChatException(
                f"User {self.user.id} is not in project chat {chat_id}"
            )

        message = await sync_to_async(ProjectChatMessage.objects.get)(
            pk=event.content["message_id"]
        )
        message.text = event.content["text"]
        message.is_edited = True
        await sync_to_async(message.save)()
        content = {
            "message_id": message.id,
            "chat_id": message.chat_id,
            "author_id": message.author.pk,
            "text": message.text,
            "created_at": message.created_at.timestamp(),
            "is_edited": message.is_edited,
        }
        await self.channel_layer.group_send(
            room_name,
            {"type": EventType.EDIT_MESSAGE, "content": content},
        )


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    # TODO: implement this
    pass
