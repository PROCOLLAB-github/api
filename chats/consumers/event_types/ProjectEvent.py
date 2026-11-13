from channels.db import database_sync_to_async

from chats.models import ProjectChat, ProjectChatMessage
from chats.project_reads import mark_project_message_read, publish_project_message_read
from chats.utils import (
    orm_exists,
    orm_get,
    orm_save,
)
from chats.services import create_project_message
from chats.websockets_settings import Event, EventType
from chats.exceptions import (
    UserNotInChatException,
    UserNotMessageAuthorException,
    UserIsNotAuthor,
)

from chats.serializers import (
    ProjectChatMessageListSerializer,
)
from projects.models import Collaborator


class ProjectEvent:
    def __init__(self, user, channel_layer, channel_name):
        self.user = user
        self.channel_layer = channel_layer
        self.channel_name = channel_name

    async def process_new_message_event(self, event: Event, room_name: str):
        chat_id = event.content["chat_id"]
        message_data, created = await database_sync_to_async(create_project_message)(
            chat_id=chat_id,
            author=self.user,
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

        event_data = {
            "type": EventType.NEW_MESSAGE,
            "content": content,
            "_project_chat_id": chat_id,
        }

        if created:
            await self.channel_layer.group_send(room_name, event_data)
        else:
            await self.channel_layer.send(self.channel_name, event_data)

    async def process_read_message_event(self, event: Event, room_name: str):
        chat_id = event.content["chat_id"]
        message_id = event.content["message_id"]
        author_id, read_count, created = await database_sync_to_async(
            mark_project_message_read
        )(chat_id=chat_id, message_id=message_id, user=self.user)
        if author_id == self.user.pk:
            return
        await publish_project_message_read(
            chat_id=chat_id,
            message_id=int(message_id),
            user_id=self.user.id,
            author_id=author_id,
            read_count=read_count,
            sender_channel=None if created else self.channel_name,
        )

    async def process_delete_message_event(self, event: Event, room_name: str):
        chat_id = event.content["chat_id"]
        chat = await orm_get(
            ProjectChat.objects.select_related("project__leader"),
            pk=chat_id,
        )

        # check that user is in this chat
        is_member = chat.project.leader_id == self.user.id or await orm_exists(
            Collaborator.objects.filter(project_id=chat.project_id, user_id=self.user.id)
        )
        if not is_member:
            raise UserNotInChatException(
                f"User {self.user.id} is not in project chat {chat_id}"
            )

        message = await orm_get(
            ProjectChatMessage.objects, pk=event.content["message_id"]
        )

        if self.user.id != message.author_id:
            raise UserIsNotAuthor(f"User {self.user.id} is not author {chat_id}")
        message.is_deleted = True
        await orm_save(message, update_fields=["is_deleted"])

        await self.channel_layer.group_send(
            room_name,
            {
                "type": EventType.DELETE_MESSAGE,
                "content": {"message_id": event.content["message_id"]},
                "_project_chat_id": event.content["chat_id"],
            },
        )

    async def process_edit_message_event(self, event, room_name):
        chat_id = event.content["chat_id"]
        chat = await orm_get(
            ProjectChat.objects.select_related("project__leader"),
            pk=chat_id,
        )

        # check that user is in this chat
        is_member = chat.project.leader_id == self.user.id or await orm_exists(
            Collaborator.objects.filter(project_id=chat.project_id, user_id=self.user.id)
        )
        if not is_member:
            raise UserNotInChatException(
                f"User {self.user.id} is not in project chat {chat_id}"
            )

        message = await orm_get(
            ProjectChatMessage.objects, pk=event.content["message_id"]
        )

        if message.author_id != self.user.id:
            raise UserNotMessageAuthorException(
                f"User {self.user.id} is not author of message {message.id}"
            )
        message.text = event.content["text"]
        message.is_edited = True
        await orm_save(message, update_fields=["text", "is_edited"])

        message_data = await database_sync_to_async(serialize_project_message)(message.pk)
        content = {
            "chat_id": chat_id,
            "message": message_data,
        }

        event_data = {
            "type": EventType.EDIT_MESSAGE,
            "content": content,
            "_project_chat_id": chat_id,
        }

        await self.channel_layer.group_send(room_name, event_data)


def serialize_project_message(message_id):
    message = (
        ProjectChatMessage.objects.select_related("author", "reply_to__author")
        .prefetch_related("file_to_message__file")
        .get(pk=message_id)
    )
    return ProjectChatMessageListSerializer(message).data
