from django.test import TestCase
from channels.testing import WebsocketCommunicator
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from django.contrib.auth import get_user_model
from chats.consumers import ChatConsumer
from asgiref.sync import sync_to_async

# from chats.tests.helpres import chat_connect
from projects.models import Project, Collaborator
from chats.models import ProjectChat, ProjectChatMessage
from chats.websockets_settings import EventType


class DirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.leader = get_user_model().objects.create(**TEST_USER1)
        cls.user = get_user_model().objects.create(**TEST_USER2)
        cls.project = Project.objects.create(leader=cls.leader)
        cls.chat = ProjectChat.objects.create(id=1, project=cls.project)
        cls.other_user = get_user_model().objects.create(**TEST_USER3)
        Collaborator.objects.create(user=cls.user, project=cls.project, role="User")

    def setUp(self):
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
        connected, subprotocol = await communicator.connect()
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
        project_message = await sync_to_async(ProjectChatMessage.objects.get)(pk=1)
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
        project_message = await sync_to_async(ProjectChatMessage.objects.get)(pk=1)
        self.assertFalse(project_message.is_read)

    async def test_delete_message_in_my_project_my_message(self):
        await self.connect(self.user)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        self.data["type"] = EventType.DELETE_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = await sync_to_async(ProjectChatMessage.objects.get)(pk=1)
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
        project_message = await sync_to_async(ProjectChatMessage.objects.get)(pk=1)
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
        project_message = await sync_to_async(ProjectChatMessage.objects.get)(pk=1)
        self.assertFalse(project_message.is_deleted)

    async def test_edit_message_in_my_project_my_message(self):
        await self.connect(self.user)
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        self.data["type"] = EventType.EDIT_MESSAGE
        self.data["content"]["message_id"] = response["content"]["message"]["id"]
        await self.communicator.send_json_to(self.data)
        response = await self.communicator.receive_json_from()
        project_message = await sync_to_async(ProjectChatMessage.objects.get)(pk=1)
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
        project_message = await sync_to_async(ProjectChatMessage.objects.get)(pk=1)
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
        project_message = await sync_to_async(ProjectChatMessage.objects.get)(pk=1)
        self.assertFalse(project_message.is_edited)
