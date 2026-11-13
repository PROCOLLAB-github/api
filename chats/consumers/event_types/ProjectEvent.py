from channels.db import database_sync_to_async

from chats.models import ProjectChat
from chats.project_reads import mark_project_message_read, publish_project_message_read
from chats.services.messages import create_project_message, delete_message, edit_message
from chats.websockets_settings import ChatType, Event, EventType


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
        message_id = await database_sync_to_async(delete_message)(
            chat_model=ProjectChat,
            chat_id=chat_id,
            message_id=event.content["message_id"],
            author=self.user,
        )

        await self.channel_layer.group_send(
            room_name,
            {
                "type": EventType.DELETE_MESSAGE,
                "content": {
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "chat_type": ChatType.PROJECT,
                },
                "_project_chat_id": chat_id,
            },
        )

    async def process_edit_message_event(self, event, room_name):
        chat_id = event.content["chat_id"]
        message_data = await database_sync_to_async(edit_message)(
            chat_model=ProjectChat,
            chat_id=chat_id,
            message_id=event.content["message_id"],
            author=self.user,
            text=event.content["text"],
        )
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
