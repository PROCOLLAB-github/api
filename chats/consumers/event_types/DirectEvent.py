from chats.models import DirectChatMessage, DirectChat
from chats.websockets_settings import Event, EventType
from chats.exceptions import (
    WrongChatIdException,
    UserNotMessageAuthorException,
    UserIsNotAuthor,
)
from django.core.cache import cache
from chats.utils import (
    get_user_channel_cache_key,
    create_message,
    get_chat_and_user_ids_from_content,
    match_files_and_messages,
    orm_create,
    orm_exists,
    orm_get,
    orm_save,
    orm_set,
)
from chats.serializers import DirectChatMessageListSerializer


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
        if not await orm_exists(DirectChat.objects.filter(pk=chat_id)):
            # if not, create such chat
            chat = await orm_create(DirectChat.objects, pk=chat_id)
            await orm_set(chat.users, [self.user, other_user])

        reply_to_message = None
        if event.content["reply_to"] is not None:
            try:
                reply_to_message = await orm_get(
                    DirectChatMessage.objects, pk=event.content["reply_to"]
                )
            except DirectChatMessage.DoesNotExist:
                reply_to_message = None

        msg = await create_message(
            chat_id=chat_id,
            chat_model=DirectChatMessage,
            author=self.user,
            text=event.content["text"],
            reply_to=reply_to_message,
        )

        messages = {
            "direct_message": msg,
            "project_message": None,
        }
        await match_files_and_messages(event.content["file_urls"], messages)

        serialized_message = await orm_get(
            DirectChatMessage.objects.select_related("author", "reply_to__author").prefetch_related(
                "file_to_message__file"
            ),
            pk=msg.pk,
        )
        message_data = DirectChatMessageListSerializer(serialized_message).data

        content = {
            "chat_id": chat_id,
            "message": message_data,
        }

        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)

        event_data = {"type": EventType.NEW_MESSAGE, "content": content}

        await self.channel_layer.send(self.channel_name, event_data)

        if other_user_channel:
            await self.channel_layer.send(other_user_channel, event_data)

    async def process_read_message_event(self, event: Event, room_name: str):
        chat_id, other_user = await get_chat_and_user_ids_from_content(
            event.content, self.user
        )
        msg = await orm_get(DirectChatMessage.objects, pk=event.content["message_id"])
        if msg.chat_id != chat_id or msg.author_id != other_user.id:
            raise WrongChatIdException(
                "Some of chat/message ids are wrong, you can't access this message"
            )
        msg.is_read = True
        await orm_save(msg, update_fields=["is_read"])
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

        message = await orm_get(DirectChatMessage.objects, pk=message_id)

        if self.user.id != message.author_id:
            raise UserIsNotAuthor(f"User {self.user.id} is not author {message.text}")

        message.is_deleted = True
        await orm_save(message, update_fields=["is_deleted"])

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

    async def process_edit_message_event(self, event, room_name):
        chat_id, other_user = await get_chat_and_user_ids_from_content(
            event.content, self.user
        )
        # if chat_id == 17_7, then chat_id will be == 7_17
        chat_id = DirectChat.get_chat_id_from_users(self.user, other_user)

        # check if chat exists ( this raises exception if not )
        await orm_get(DirectChat.objects, pk=chat_id)

        msg = await orm_get(DirectChatMessage.objects, pk=event.content["message_id"])

        if msg.author_id != self.user.id:
            raise UserNotMessageAuthorException(
                f"User {self.user.id} is not author of message {msg.id}"
            )
        msg.text = event.content["text"]
        msg.is_edited = True
        await orm_save(msg, update_fields=["text", "is_edited"])

        serialized_message = await orm_get(
            DirectChatMessage.objects.select_related("author", "reply_to__author").prefetch_related(
                "file_to_message__file"
            ),
            pk=msg.pk,
        )
        message_data = DirectChatMessageListSerializer(serialized_message).data
        content = {
            "chat_id": chat_id,
            "message": message_data,
        }

        # send message to user's channel
        other_user_channel = cache.get(get_user_channel_cache_key(other_user), None)

        event_data = {"type": EventType.EDIT_MESSAGE, "content": content}

        if other_user_channel:
            await self.channel_layer.send(other_user_channel, event_data)

        await self.channel_layer.send(self.channel_name, event_data)
