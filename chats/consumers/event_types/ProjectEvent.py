from chats.models import ProjectChat, ProjectChatMessage
from chats.utils import (
    create_message,
    match_files_and_messages,
    orm_exists,
    orm_get,
    orm_save,
)
from chats.websockets_settings import Event, EventType
from chats.exceptions import (
    WrongChatIdException,
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

        reply_to_message = None
        if event.content["reply_to"] is not None:
            try:
                reply_to_message = await orm_get(
                    ProjectChatMessage.objects, pk=event.content["reply_to"]
                )
            except ProjectChatMessage.DoesNotExist:
                reply_to_message = None

        msg = await create_message(
            chat_id=chat_id,
            chat_model=ProjectChatMessage,
            author=self.user,
            text=event.content["text"],
            reply_to=reply_to_message,
        )

        messages = {
            "direct_message": None,
            "project_message": msg,
        }
        await match_files_and_messages(event.content["file_urls"], messages)

        serialized_message = await orm_get(
            ProjectChatMessage.objects.select_related("author", "reply_to__author").prefetch_related(
                "file_to_message__file"
            ),
            pk=msg.pk,
        )
        message_data = ProjectChatMessageListSerializer(serialized_message).data
        content = {
            "chat_id": chat_id,
            "message": message_data,
        }

        event_data = {"type": EventType.NEW_MESSAGE, "content": content}

        await self.channel_layer.group_send(room_name, event_data)

    async def process_read_message_event(self, event: Event, room_name: str):
        msg = await orm_get(ProjectChatMessage.objects, pk=event.content["message_id"])
        chat = await orm_get(
            ProjectChat.objects.select_related("project__leader"),
            pk=msg.chat_id,
        )
        # check that user is in this chat
        is_member = chat.project.leader_id == self.user.id or await orm_exists(
            Collaborator.objects.filter(project_id=chat.project_id, user_id=self.user.id)
        )
        if not is_member:
            raise UserNotInChatException(
                f"User {self.user.id} is not in project chat {msg.chat_id}"
            )
        if msg.chat_id != int(event.content["chat_id"]):
            raise WrongChatIdException(
                "Some of chat/message ids are wrong, you can't access this message"
            )
        msg.is_read = True
        await orm_save(msg, update_fields=["is_read"])
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

        message = await orm_get(ProjectChatMessage.objects, pk=event.content["message_id"])

        if self.user.id != message.author_id:
            raise UserIsNotAuthor(f"User {self.user.id} is not author {chat_id}")
        message.is_deleted = True
        await orm_save(message, update_fields=["is_deleted"])

        await self.channel_layer.group_send(
            room_name,
            {
                "type": EventType.DELETE_MESSAGE,
                "content": {"message_id": event.content["message_id"]},
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

        message = await orm_get(ProjectChatMessage.objects, pk=event.content["message_id"])

        if message.author_id != self.user.id:
            raise UserNotMessageAuthorException(
                f"User {self.user.id} is not author of message {message.id}"
            )
        message.text = event.content["text"]
        message.is_edited = True
        await orm_save(message, update_fields=["text", "is_edited"])

        serialized_message = await orm_get(
            ProjectChatMessage.objects.select_related("author", "reply_to__author").prefetch_related(
                "file_to_message__file"
            ),
            pk=message.pk,
        )
        message_data = ProjectChatMessageListSerializer(serialized_message).data
        content = {
            "chat_id": chat_id,
            "message": message_data,
        }

        event_data = {"type": EventType.EDIT_MESSAGE, "content": content}

        await self.channel_layer.group_send(room_name, event_data)
