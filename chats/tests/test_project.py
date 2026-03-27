from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from chats.consumers import ChatConsumer
from chats.models import ProjectChat, ProjectChatMessage
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.websockets_settings import EventType

# from chats.tests.helpres import chat_connect -
from projects.models import Project, Collaborator


class DirectTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        self.leader = get_user_model().objects.create(**TEST_USER1)
        self.user = get_user_model().objects.create(**TEST_USER2)
        self.project = Project.objects.create(leader=self.leader)
        self.chat = ProjectChat.objects.create(id=1, project=self.project)
        self.other_user = get_user_model().objects.create(**TEST_USER3)
        Collaborator.objects.create(user=self.user, project=self.project, role="User")
        self.data = {
            "type": EventType.NEW_MESSAGE,
            "content": {
                "chat_type": "project",
                "chat_id": "1",
                "text": "hello world",
                "reply_to": None,
                "file_urls": [],
            },
        }

    async def connect(self, user):
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect(timeout=5)
        self.assertTrue(connected)
        self.communicator = communicator

    async def test_connect(self):
        await self.connect(self.user)

    async def test_new_message_in_my_project_with_leader_account(self):
        await self.connect(self.leader)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        self.assertFalse("error" in response.keys())

    async def test_new_message_in_my_project_without_leader_account(self):
        await self.connect(self.user)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        self.assertFalse("error" in response.keys())

    async def test_new_message_in_other_project(self):
        await self.connect(self.other_user)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        self.assertTrue("error" in response.keys())

    async def test_read_message_in_my_project_other_message(self):
        await self.connect(self.user)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        await self.communicator.disconnect()

        await self.connect(self.leader)
        self.data["type"] = EventType.READ_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = ProjectChatMessage.objects.get(pk=1)
        self.assertTrue(project_message.is_read)

    async def test_read_message_in_other_project_other_message(self):
        await self.connect(self.user)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        await self.communicator.disconnect()

        await self.connect(self.other_user)
        self.data["type"] = EventType.READ_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = ProjectChatMessage.objects.get(pk=1)
        self.assertFalse(project_message.is_read)

    async def test_delete_message_in_my_project_my_message(self):
        await self.connect(self.user)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        self.data["type"] = EventType.DELETE_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = ProjectChatMessage.objects.get(pk=1)
        self.assertTrue(project_message.is_deleted)

    async def test_delete_message_in_my_project_other_message(self):
        await self.connect(self.leader)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        await self.communicator.disconnect()

        await self.connect(self.user)
        self.data["type"] = EventType.DELETE_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = ProjectChatMessage.objects.get(pk=1)
        self.assertFalse(project_message.is_deleted)

    async def test_delete_message_in_other_project_other_message(self):
        await self.connect(self.leader)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        await self.communicator.disconnect()

        await self.connect(self.other_user)
        self.data["type"] = EventType.DELETE_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = ProjectChatMessage.objects.get(pk=1)
        self.assertFalse(project_message.is_deleted)

    async def test_edit_message_in_my_project_my_message(self):
        await self.connect(self.user)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        self.data["type"] = EventType.EDIT_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = ProjectChatMessage.objects.get(pk=1)
        self.assertTrue(project_message.is_edited)

    async def test_edit_message_in_my_project_other_message(self):
        await self.connect(self.leader)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        await self.communicator.disconnect()

        await self.connect(self.user)
        self.data["type"] = EventType.EDIT_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = ProjectChatMessage.objects.get(pk=1)
        self.assertFalse(project_message.is_edited)

    async def test_edit_message_other_my_project_other_message(self):
        await self.connect(self.leader)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        await self.communicator.disconnect()

        await self.connect(self.other_user)
        self.data["type"] = EventType.EDIT_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = ProjectChatMessage.objects.get(pk=1)
        self.assertFalse(project_message.is_edited)
