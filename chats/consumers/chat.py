import datetime
import json
from json import JSONDecodeError
from typing import Optional

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from chats.channel_events import channel_group
from chats.direct_privacy import direct_chat_opponent, direct_contact
from chats.exceptions import ChatException
from chats.permissions import accessible_chats, direct_chat_is_accessible
from chats.project_reads import personalize_project_message_event
from chats.services.messages import get_direct_chat_for_typing
from chats.utils import get_user_channel_cache_key
from chats.websockets_settings import (
    Event,
    EventType,
    EventGroupType,
    ChatType,
)
from core.constants import ONE_DAY_IN_SECONDS, ONE_WEEK_IN_SECONDS
from core.utils import get_user_online_cache_key, get_users_online_cache_key
from users.models import CustomUser
from chats.consumers.event_types import DirectEvent, ProjectEvent
from chats.utils import get_chat_and_user_ids_from_content
from chats.models import DirectChat, ProgramChannel, ProgramChannelMessage, ProjectChat
from chats.notifications import should_notify


@database_sync_to_async
def get_user_project_ids(user) -> list[int]:
    return list(accessible_chats(user, ProjectChat).values_list("pk", flat=True))


@database_sync_to_async
def can_access_project_chat(user, chat_id):
    return accessible_chats(user, ProjectChat).filter(pk=chat_id).exists()


@database_sync_to_async
def get_user_channel_ids(user):
    return list(accessible_chats(user, ProgramChannel).values_list("pk", flat=True))


@database_sync_to_async
def can_access_program_channel(user, channel_id):
    return accessible_chats(user, ProgramChannel).filter(pk=channel_id).exists()


@database_sync_to_async
def channel_notification(user, channel_id, message_id):
    message = (
        ProgramChannelMessage.objects.filter(
            chat_id=channel_id, pk=message_id, is_deleted=False
        )
        .values("author_id", "mentioned_user_ids")
        .first()
    )
    return bool(message and should_notify(user, ProgramChannel, channel_id, **message))


@database_sync_to_async
def can_receive_direct_typing(user, chat_id):
    chat = accessible_chats(user, DirectChat).filter(pk=chat_id).first()
    if chat is None:
        return False
    try:
        other = direct_chat_opponent(chat, user)
    except ChatException:
        return False
    return direct_contact(other, user, chat).can_send


class ChatConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user: Optional[CustomUser] = None
        self.joined_rooms: set[str] = set()

    async def connect(self):
        """User connected to websocket"""

        if self.scope["user"].is_anonymous:
            # not authenticated
            return await self.close(403)

        self.user = self.scope["user"]
        cache.set(
            get_user_channel_cache_key(self.user), self.channel_name, ONE_WEEK_IN_SECONDS
        )

        if not settings.RUNNING_TESTS:
            project_ids_list = await get_user_project_ids(self.user)
            for project_id in project_ids_list:
                await self._ensure_room_subscription(
                    f"{EventGroupType.CHATS_RELATED}_{project_id}"
                )
            for channel_id in await get_user_channel_ids(self.user):
                await self._ensure_room_subscription(channel_group(channel_id))

        # set user online
        user_cache_key = get_user_online_cache_key(self.user)
        cache.set(user_cache_key, True, ONE_DAY_IN_SECONDS)
        online_users = cache.get(get_users_online_cache_key(), set())
        online_users.add(self.user.id)
        cache.set(get_users_online_cache_key(), online_users)
        # notify everyone that this user is online
        await self.channel_layer.group_send(
            EventGroupType.GENERAL_EVENTS,
            {"type": EventType.SET_ONLINE, "content": {"user_id": self.user.id}},
        )

        # add to group to listen for general events, like online/offline
        await self.channel_layer.group_add(
            EventGroupType.GENERAL_EVENTS, self.channel_name
        )
        # Confirm selected subprotocol so browser clients finish handshake.
        subprotocol = None
        if self.scope.get("subprotocols") and len(self.scope["subprotocols"]) >= 1:
            subprotocol = self.scope["subprotocols"][0]

        await self.accept(subprotocol=subprotocol)

    async def _ensure_room_subscription(self, room_name: str):
        if room_name in self.joined_rooms:
            return

        await self.channel_layer.group_add(room_name, self.channel_name)
        self.joined_rooms.add(room_name)

    async def disconnect(self, close_code):
        """User disconnected from websocket"""
        if not self.user or self.user.is_anonymous:
            # don't need to proccess logic for disconnect
            #  if we are not logged in!
            return
        for room_name in self.joined_rooms:
            await self.channel_layer.group_discard(room_name, self.channel_name)
        self.joined_rooms.clear()
        await self.channel_layer.group_discard(
            EventGroupType.GENERAL_EVENTS, self.channel_name
        )
        user_channel_key = get_user_channel_cache_key(self.user)
        if cache.get(user_channel_key) != self.channel_name:
            return
        cache.delete(user_channel_key)
        online_users = cache.get(get_users_online_cache_key(), set())
        online_users.discard(self.user.id)
        cache.set(get_users_online_cache_key(), online_users)
        cache.delete(get_user_online_cache_key(self.user))
        room_name = EventGroupType.GENERAL_EVENTS

        # TODO: add a User extra-small serializer for this?
        await self.channel_layer.group_send(
            room_name,
            {"type": EventType.SET_OFFLINE, "content": {"user_id": self.user.id}},
        )

    async def receive_json(self, content, **kwargs):
        """Receive message from WebSocket in JSON format"""

        if not isinstance(content, dict) or not isinstance(content.get("type"), str):
            await self.send_json({"error": "Некорректный формат события."})
            return
        event = Event(type=content["type"], content=content.get("content"))

        # two event types - related to group chat and related to leave/connect
        if event.type in [
            EventType.NEW_MESSAGE,
            EventType.TYPING,
            EventType.READ_MESSAGE,
            EventType.DELETE_MESSAGE,
            EventType.EDIT_MESSAGE,
        ]:
            if not isinstance(event.content, dict):
                await self.send_json({"error": "Некорректные данные события."})
                return
            chat_type = event.content.get("chat_type")
            chat_id = event.content.get("chat_id")
            room_name = ""
            if chat_type == ChatType.DIRECT:
                handler = DirectEvent(self.user, self.channel_layer, self.channel_name)
            elif chat_type == ChatType.PROJECT:
                try:
                    if type(chat_id) not in (int, str):
                        raise ValueError
                    project_id = int(chat_id)
                except ValueError:
                    await self.send_json({"error": "Некорректный идентификатор чата."})
                    return
                if not await can_access_project_chat(self.user, project_id):
                    await self.send_json({"error": "У вас нет доступа к чату проекта."})
                    return
                handler = ProjectEvent(self.user, self.channel_layer, self.channel_name)
                room_name = f"{EventGroupType.CHATS_RELATED}_{project_id}"
                await self._ensure_room_subscription(room_name)
            else:
                await self.send_json({"error": "Неизвестный тип чата."})
                return
            try:
                await self.__process_chat_related_event(handler, event, room_name)
            except ChatException as e:
                await self.send_json({"error": str(e.get_error())})
            except KeyError as e:
                await self.send_json({"error": f"В запросе отсутствует поле {e}."})

        elif event.type == EventType.SUBSCRIBE_PROGRAM_CHANNEL:
            await self.subscribe_program_channel(event.content)
        elif event.type in [EventType.SET_ONLINE, EventType.SET_OFFLINE]:
            room_name = EventGroupType.GENERAL_EVENTS
            await self.__process_general_event(event, room_name)
        else:
            await self.send_json({"error": "Неизвестный тип события."})

    async def __process_chat_related_event(self, handler, event, room_name):
        if event.type == EventType.NEW_MESSAGE:
            await handler.process_new_message_event(event, room_name)
        elif event.type == EventType.TYPING:
            await self.__process_typing_event(event, room_name)
        elif event.type == EventType.READ_MESSAGE:
            await handler.process_read_message_event(event, room_name)
        elif event.type == EventType.DELETE_MESSAGE:
            await handler.process_delete_message_event(event, room_name)
        elif event.type == EventType.EDIT_MESSAGE:
            await handler.process_edit_message_event(event, room_name)

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

        if event.content["chat_type"] == ChatType.PROJECT:
            event_data["_project_chat_id"] = event.content["chat_id"]
            await self.channel_layer.group_send(room_name, event_data)

        else:
            _, other_user = await get_chat_and_user_ids_from_content(
                event.content, self.user
            )

            chat = await database_sync_to_async(get_direct_chat_for_typing)(
                self.user, other_user
            )
            event_data["content"]["chat_id"] = chat.pk
            event_data["_direct_chat_id"] = chat.pk

            # send message to user's channel
            other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)

            if other_user_channel and other_user_channel != self.channel_name:
                await self.channel_layer.send(other_user_channel, event_data)

    async def _send_chat_event(self, event):
        direct_chat_id = event.get("_direct_chat_id")
        if direct_chat_id is not None:
            check_access = (
                can_receive_direct_typing
                if event["type"] == EventType.TYPING
                else database_sync_to_async(direct_chat_is_accessible)
            )
            if not self.user or not await check_access(self.user, direct_chat_id):
                return
        chat_id = event.get("_project_chat_id")
        if chat_id is not None:
            if not self.user or not await can_access_project_chat(self.user, chat_id):
                room_name = f"{EventGroupType.CHATS_RELATED}_{int(chat_id)}"
                await self.channel_layer.group_discard(room_name, self.channel_name)
                self.joined_rooms.discard(room_name)
                return
            audience = event.get("_project_read_audience")
            if audience is not None and self.user.pk not in audience:
                return
            if event["type"] in (EventType.NEW_MESSAGE, EventType.EDIT_MESSAGE):
                content = event["content"]
                message = await database_sync_to_async(personalize_project_message_event)(
                    content["message"], self.user.pk
                )
                event = {**event, "content": {**content, "message": message}}
                if event["type"] == EventType.NEW_MESSAGE:
                    notify = not content.get(
                        "is_replay"
                    ) and await database_sync_to_async(should_notify)(
                        self.user,
                        ProjectChat,
                        chat_id,
                        author_id=message["author"]["id"],
                        mentioned_user_ids=message.get("mentioned_user_ids", []),
                    )
                    event["content"]["notify"] = notify
        # Служебный контекст нужен для проверки уже открытых сокетов,
        # клиентский формат сообщений остается прежним.
        await self.send(
            json.dumps(
                {key: value for key, value in event.items() if not key.startswith("_")}
            )
        )

    async def message_read(self, event: Event):
        await self._send_chat_event(event)

    async def user_typing(self, event: Event):
        await self._send_chat_event(event)

    async def new_message(self, event: Event):
        await self._send_chat_event(event)

    async def delete_message(self, event: Event):
        await self._send_chat_event(event)

    async def set_online(self, event: Event):
        await self.send(json.dumps(event))

    async def set_offline(self, event: Event):
        await self.send(json.dumps(event))

    async def edit_message(self, event: Event):
        await self._send_chat_event(event)

    async def subscribe_program_channel(self, content):
        channel_id = content.get("channel_id") if isinstance(content, dict) else None
        if type(channel_id) is not int or not 0 < channel_id < 2**63:
            await self.send_json({"error": "Некорректный идентификатор канала."})
            return
        if not await can_access_program_channel(self.user, channel_id):
            await self.send_json({"error": "Канал недоступен."})
            return
        await self._ensure_room_subscription(channel_group(channel_id))
        await self.send_json(
            {
                "type": EventType.SUBSCRIBE_PROGRAM_CHANNEL,
                "content": {"channel_id": channel_id},
            }
        )

    async def program_channel_changed(self, event):
        channel_id = event["content"]["channel_id"]
        if self.user and await can_access_program_channel(self.user, channel_id):
            message_id = event.get("_new_message_id")
            notify = message_id is not None and await channel_notification(
                self.user, channel_id, message_id
            )
            content = {"channel_id": channel_id, "notify": notify}
            if notify:
                content["message_id"] = message_id
            await self.send_json({"type": event["type"], "content": content})
        else:
            room_name = channel_group(channel_id)
            await self.channel_layer.group_discard(room_name, self.channel_name)
            self.joined_rooms.discard(room_name)

    async def __process_general_event(self, event: Event, room_name: str):
        cache_key = get_user_online_cache_key(self.user)
        users_online_list_key = get_users_online_cache_key()
        if event.type == EventType.SET_ONLINE:
            cache.set(cache_key, True, ONE_DAY_IN_SECONDS)
            users_online_list = cache.get_or_set(users_online_list_key, set())
            users_online_list.add(self.user.pk)
            cache.set(users_online_list_key, users_online_list, ONE_DAY_IN_SECONDS)

            # sent everyone online event that user X is online
            await self.channel_layer.group_send(
                room_name, {"type": EventType.SET_ONLINE, "user_id": self.user.pk}
            )
        elif event.type == EventType.SET_OFFLINE:
            cache.delete(cache_key)
            users_online_list = cache.get_or_set(users_online_list_key, set())
            users_online_list.discard(self.user.pk)
            cache.set(users_online_list_key, users_online_list, ONE_DAY_IN_SECONDS)

            # sent everyone online event that user X is offline
            await self.channel_layer.group_send(
                room_name, {"type": EventType.SET_OFFLINE, "user_id": self.user.pk}
            )

            # TODO: close connection here?
            # await self.close(200)
        else:
            raise ValueError("Unknown event type")

    async def decode_json(self, text_data) -> dict:
        try:
            return json.loads(text_data)
        except JSONDecodeError:
            return {}
