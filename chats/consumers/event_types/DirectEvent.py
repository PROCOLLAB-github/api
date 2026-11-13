from channels.db import database_sync_to_async

from chats.direct_reads import mark_direct_message_read, publish_direct_message_read
from chats.models import DirectChat
from chats.websockets_settings import ChatType, Event, EventType
from django.core.cache import cache
from chats.utils import (
    get_user_channel_cache_key,
    get_chat_and_user_ids_from_content,
)
from chats.services.messages import (
    create_direct_message,
    delete_message,
    edit_message,
)


class DirectEvent:
    def __init__(self, user, channel_layer, channel_name):
        self.user = user
        self.channel_layer = channel_layer
        self.channel_name = channel_name

    async def process_new_message_event(self, event: Event, room_name: str):
        _, other_user = await get_chat_and_user_ids_from_content(event.content, self.user)
        chat_id = DirectChat.get_chat_id_from_users(self.user, other_user)

        message_data, created = await database_sync_to_async(create_direct_message)(
            author=self.user,
            other_user=other_user,
            text=event.content.get("text", ""),
            reply_to_id=event.content.get("reply_to"),
            file_urls=event.content.get("file_urls", []),
            client_message_id=event.content.get("client_message_id"),
        )

        content = {
            "chat_id": chat_id,
            "message": message_data,
            "is_replay": not created,
        }

        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)

        event_data = {
            "type": EventType.NEW_MESSAGE,
            "content": content,
            "_direct_chat_id": chat_id,
        }

        await self.channel_layer.send(self.channel_name, event_data)

        if created and other_user_channel and other_user_channel != self.channel_name:
            await self.channel_layer.send(other_user_channel, event_data)

    async def process_read_message_event(self, event: Event, room_name: str):
        _, other_user = await get_chat_and_user_ids_from_content(event.content, self.user)
        chat_id = DirectChat.get_chat_id_from_users(self.user, other_user)
        message_id = await database_sync_to_async(mark_direct_message_read)(
            chat_id=chat_id,
            message_id=event.content["message_id"],
            user=self.user,
            author=other_user,
        )
        await publish_direct_message_read(
            chat_id=chat_id,
            message_id=message_id,
            user=self.user,
            author=other_user,
            sender_channel=self.channel_name,
        )

    async def process_delete_message_event(self, event: Event, room_name: str):
        _, other_user = await get_chat_and_user_ids_from_content(event.content, self.user)
        chat_id = DirectChat.get_chat_id_from_users(self.user, other_user)
        message_id = await database_sync_to_async(delete_message)(
            chat_model=DirectChat,
            chat_id=chat_id,
            message_id=event.content["message_id"],
            author=self.user,
        )

        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)
        event_data = {
            "type": EventType.DELETE_MESSAGE,
            "content": {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": ChatType.DIRECT,
            },
            "_direct_chat_id": chat_id,
        }
        await self.channel_layer.send(self.channel_name, event_data)

        if other_user_channel and other_user_channel != self.channel_name:
            await self.channel_layer.send(other_user_channel, event_data)

    async def process_edit_message_event(self, event, room_name):
        _, other_user = await get_chat_and_user_ids_from_content(event.content, self.user)
        chat_id = DirectChat.get_chat_id_from_users(self.user, other_user)
        message_data = await database_sync_to_async(edit_message)(
            chat_model=DirectChat,
            chat_id=chat_id,
            message_id=event.content["message_id"],
            author=self.user,
            text=event.content["text"],
        )
        content = {
            "chat_id": chat_id,
            "message": message_data,
        }

        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)

        event_data = {
            "type": EventType.EDIT_MESSAGE,
            "content": content,
            "_direct_chat_id": chat_id,
        }

        if other_user_channel and other_user_channel != self.channel_name:
            await self.channel_layer.send(other_user_channel, event_data)

        await self.channel_layer.send(self.channel_name, event_data)
