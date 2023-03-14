from asgiref.sync import sync_to_async
from chats.models import ProjectChat, ProjectChatMessage
from chats.utils import create_message
from chats.websockets_settings import Event, EventType, ChatType
from chats.exceptions import (
    WrongChatIdException,
    UserNotInChatException,
)


class ProjectEvent:
    def __init__(self, user, channel_layer, channel_name):
        self.user = user
        self.channel_layer = channel_layer
        self.channel_name = channel_name

    async def process_new_message_event(self, event: Event, room_name: str):
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
            # file_url=event.content["file_url"],
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
                },
            },
        )

    async def process_read_message_event(self, event: Event, room_name: str):
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

    async def process_delete_message_event(self, event: Event, room_name: str):
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
