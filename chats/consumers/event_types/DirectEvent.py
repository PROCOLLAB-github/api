from chats.models import DirectChatMessage, DirectChat
from chats.websockets_settings import Event, EventType
from asgiref.sync import sync_to_async
from chats.exceptions import WrongChatIdException
from django.core.cache import cache
from chats.utils import (
    get_user_channel_cache_key,
    create_message,
    get_chat_and_user_ids_from_content,
)


class DirectEvent:
    def __init__(self, user, channel_layer, channel_name):
        self.user = user
        self.channel_layer = channel_layer
        self.channel_name = channel_name

    async def process_new_message_event(self, event: Event, room_name: str):
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
            # file_url=event.content["file_url"],
        )

        content = {
            "type": EventType.NEW_MESSAGE,
            "content": {
                "message_id": msg.id,
                "chat_id": msg.chat_id,
                "author_id": msg.author.pk,
                "text": msg.text,
                "created_at": msg.created_at.timestamp(),
            },
        }
        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)
        await self.channel_layer.send(self.channel_name, content)

        if other_user_channel is None:
            return

        await self.channel_layer.send(other_user_channel, content)

    async def process_read_message_event(self, event: Event, room_name: str):
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

    async def process_delete_message_event(self, event: Event, room_name: str):
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
