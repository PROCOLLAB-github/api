import json
from typing import Optional

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache

from chats.exceptions import (
    NonMatchingDirectChatIdException,
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
        event = Event(
            type=content["type"],
            content=Content(
                **content.get(
                    "content",
                    {
                        "chat_id": None,
                        "message": None,
                        "chat_type": None,
                        "reply_to": None,
                    },
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
            try:
                await self.__process_chat_related_event(event, room_name)
            except ChatException as e:
                await self.send_json({"error": str(e.get_error())})

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
                try:
                    user1_id, user2_id = map(int, chat_id.split("_"))
                except ValueError:
                    raise WrongChatIdException(
                        f'Chat id "{chat_id}" is not in the format of'
                        f" <user1_id>_<user2_id>, where user1_id < user2_id"
                    )
                if user1_id == self.user.id or user2_id == self.user.id:
                    other_user = await sync_to_async(CustomUser.objects.get)(
                        id=user1_id if user1_id != self.user.id else user2_id
                    )
                else:
                    raise NonMatchingDirectChatIdException(
                        f"User {self.user.id} is not a member of chat {chat_id}"
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
                # TODO: check that content.reply_to is a message in this chat. maybe constraint?
                msg = await sync_to_async(DirectChatMessage.objects.create)(
                    # reply_to=event.content.reply_to,
                    chat_id=chat_id,
                    author=self.user,
                    text=event.content.message,
                )
                # send message to user's channel
                other_user_channel = cache.get(
                    get_user_channel_cache_key(other_user), None
                )
                await self.channel_layer.send(
                    self.channel_name,
                    {
                        "type": "chat_message",
                        "message": {
                            "id": msg.id,
                            "chat_id": msg.chat_id,
                            "author_id": msg.author.pk,
                            "text": msg.text,
                            "created_at": msg.created_at.timestamp(),
                        },
                    },
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
                            "chat_type": ChatType.DIRECT,
                            "author_id": msg.author.pk,
                            "text": msg.text,
                            "created_at": msg.created_at.timestamp(),
                        },
                    },
                )
            else:
                # create new message
                chat_id = event.content.chat_id
                chat = await sync_to_async(ProjectChat.objects.get)(pk=chat_id)
                # check that user is in this chat
                users = await sync_to_async(chat.get_users)()
                if self.user not in users:
                    raise UserNotInChatException(
                        f"User {self.user.id} is not in project chat {chat_id}"
                    )

                msg = await sync_to_async(ProjectChatMessage.objects.create)(
                    reply_to=event.content.reply_to,
                    chat=chat,
                    author=self.user,
                    text=event.content.message,
                )
                await self.channel_layer.group_send(
                    room_name,
                    {
                        "type": "chat_message",
                        "message": {
                            "id": msg.id,
                            "chat_id": msg.chat_id,
                            "chat_type": ChatType.PROJECT,
                            "author_id": msg.author.pk,
                            "text": msg.text,
                            "created_at": msg.created_at.timestamp(),
                        },
                    },
                )
                pass

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

            # TODO: close connection here?
            # await self.close(200)
        else:
            raise ValueError("Unknown event type")


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    # TODO: implement this
    pass
