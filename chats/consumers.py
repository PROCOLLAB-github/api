from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

from chats.models import ProjectChat, DirectChat, DirectChatMessage, ProjectChatMessage
from chats.utils import clean_message_text, validate_message_text
from chats.websockets_settings import ChatType, EventType
from projects.models import Project
from users.models import CustomUser


class ChatConsumer(JsonWebsocketConsumer):
    ROOM_TYPES = {
        "DIRECT": "direct",
        "PROJECT": "project",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.room_name = None
        self.user = None
        self.chat_type = None
        self.chat = None

    def connect(self):
        # authentication
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            return

        room_name = self.scope["url_route"]["kwargs"]["room_name"]
        if room_name.startswith("direct"):
            other_user_id = int(room_name.split("_")[1])
            other_user = CustomUser.objects.filter(id=other_user_id).first()

            if not other_user or other_user_id == self.user.id:
                # such user does not exist / user tries to chat with himself
                self.close()
                return

            user1_id = min(self.user.pk, other_user_id)
            user2_id = max(self.user.pk, other_user_id)

            self.room_name = f"direct_{user1_id}_{user2_id}"
            self.chat_type = "direct"
            self.chat = DirectChat.objects.get_chat(self.user, other_user)

        elif room_name.startswith("project"):
            project_id = int(room_name.split("_")[1])

            filtered_projects = Project.objects.filter(id=project_id)

            if not filtered_projects.exists():
                # project does not exist
                self.close()
                return

            if (
                not filtered_projects.first()
                .collaborators.filter(user=self.user)
                .exists()
            ):
                # user is not a collaborator
                self.close()
                return

            self.room_name = f"project_{project_id}"
            self.chat_type = "project"
            self.chat = ProjectChat.objects.get(project_id=project_id)

        # Join room group
        async_to_sync(self.channel_layer.group_add)(self.room_name, self.channel_name)

        self.accept()

    def disconnect(self, close_code):
        # Leave room group
        async_to_sync(self.channel_layer.group_discard)(self.room_name, self.channel_name)

    # Receive message from WebSocket
    def receive_json(self, content, **kwargs):
        message_type = content["type"]

        if message_type == EventType.CHAT_MESSAGE.value:
            self.__process_new_message(content)
        elif message_type == EventType.TYPING.value:
            # TODO
            pass
        elif message_type == EventType.READ.value:
            # TODO
            pass

    def __process_new_message(self, content):
        text = clean_message_text(content["text"])
        if not validate_message_text(text):
            return

        if self.chat_type == ChatType.DIRECT.value:  # TODO: replace with enum
            DirectChatMessage.objects.create(chat=self.chat, author=self.user, text=text)
        elif self.chat_type == ChatType.PROJECT.value:
            ProjectChatMessage.objects.create(chat=self.chat, author=self.user, text=text)
        else:
            return

        async_to_sync(self.channel_layer.group_send)(
            self.room_name,
            {
                "type": "chat_message_echo",
                "name": content["name"],
                "message": text,
            },
        )


class NotificationConsumer(JsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.user = None

    def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            return

        self.accept()

        # Send count of unread messages
