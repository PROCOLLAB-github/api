from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature

from chats.consumers import ChatConsumer
from chats.models import DirectChat, DirectChatMessage, FileToMessage, ProjectChat
from chats.models import ProjectChatMessage
from chats.services import create_direct_message, create_project_message
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from files.models import UserFile
from projects.models import Collaborator, Project


class MessageDeliveryTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create(**TEST_USER1)

    async def connect(self, user=None):
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user or self.user
        connected, _ = await communicator.connect(timeout=5)
        self.assertTrue(connected)
        return communicator

    @staticmethod
    def direct_message(chat_id, **overrides):
        content = {
            "chat_type": "direct",
            "chat_id": chat_id,
            "text": "Тестовое сообщение",
            "reply_to": None,
            "file_urls": [],
            "client_message_id": str(uuid4()),
        }
        content.update(overrides)
        return {"type": "new_message", "content": content}

    async def test_direct_retry_returns_original_message_without_duplicate(self):
        communicator = await self.connect()
        data = self.direct_message("1_1")

        await communicator.send_json_to(data)
        first_response = await communicator.receive_json_from()
        await communicator.send_json_to(data)
        second_response = await communicator.receive_json_from()

        self.assertEqual(DirectChatMessage.objects.count(), 1)
        self.assertEqual(
            first_response["content"]["message"]["id"],
            second_response["content"]["message"]["id"],
        )
        self.assertFalse(first_response["content"]["is_replay"])
        self.assertTrue(second_response["content"]["is_replay"])
        self.assertEqual(
            second_response["content"]["message"]["client_message_id"],
            data["content"]["client_message_id"],
        )
        self.assertTrue(await communicator.receive_nothing())
        await communicator.disconnect()

    async def test_file_only_message_can_be_retried(self):
        user_file = UserFile.objects.create(
            link="https://cdn.example.test/chat-file.pdf",
            user=self.user,
            name="chat-file",
            extension="pdf",
            mime_type="application/pdf",
            detected_mime_type="application/pdf",
            size=128,
        )
        communicator = await self.connect()
        data = self.direct_message(
            "1_1",
            text="",
            file_urls=[user_file.pk],
        )

        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        await communicator.send_json_to(data)
        replay = await communicator.receive_json_from()

        self.assertNotIn("error", response)
        self.assertEqual(DirectChatMessage.objects.count(), 1)
        self.assertEqual(FileToMessage.objects.count(), 1)
        self.assertEqual(len(response["content"]["message"]["files"]), 1)
        self.assertTrue(replay["content"]["is_replay"])
        self.assertEqual(replay["content"]["message"], response["content"]["message"])
        await communicator.disconnect()

    async def test_file_from_another_account_is_rejected(self):
        other_user = get_user_model().objects.create(**TEST_USER2)
        user_file = UserFile.objects.create(
            link="https://cdn.example.test/foreign-file.pdf",
            user=other_user,
            name="foreign-file",
            extension="pdf",
            mime_type="application/pdf",
            detected_mime_type="application/pdf",
            size=128,
        )
        communicator = await self.connect()
        data = self.direct_message("1_1", file_urls=[user_file.pk])

        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()

        self.assertIn("error", response)
        self.assertEqual(DirectChatMessage.objects.count(), 0)
        self.assertEqual(DirectChat.objects.count(), 0)
        await communicator.disconnect()

    async def test_reply_to_another_chat_is_rejected(self):
        get_user_model().objects.create(**TEST_USER2)
        get_user_model().objects.create(**TEST_USER3)
        communicator = await self.connect()

        await communicator.send_json_to(self.direct_message("1_2"))
        first_response = await communicator.receive_json_from()
        reply_id = first_response["content"]["message"]["id"]
        await communicator.send_json_to(self.direct_message("1_3", reply_to=reply_id))
        response = await communicator.receive_json_from()

        self.assertIn("error", response)
        self.assertEqual(DirectChatMessage.objects.count(), 1)
        await communicator.disconnect()


class ProjectMessageDeliveryTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        self.leader = get_user_model().objects.create(**TEST_USER1)
        self.member = get_user_model().objects.create(**TEST_USER2)
        self.project = Project.objects.create(leader=self.leader)
        self.chat, _ = ProjectChat.objects.get_or_create(
            id=self.project.pk,
            defaults={"project": self.project},
        )
        Collaborator.objects.create(
            user=self.member,
            project=self.project,
            role="User",
        )

    async def connect(self, user):
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, _ = await communicator.connect(timeout=5)
        self.assertTrue(connected)
        return communicator

    @override_settings(RUNNING_TESTS=False)
    async def test_project_retry_is_not_broadcast_as_a_new_message(self):
        client_message_id = str(uuid4())
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "project",
                "chat_id": str(self.chat.pk),
                "text": "Сообщение проекта",
                "reply_to": None,
                "file_urls": [],
                "client_message_id": client_message_id,
            },
        }
        communicator = await self.connect(self.member)
        recipient = await self.connect(self.leader)
        self.assertEqual((await communicator.receive_json_from())["type"], "set_online")

        await communicator.send_json_to(data)
        first_response = await communicator.receive_json_from()
        self.assertEqual(await recipient.receive_json_from(), first_response)
        await communicator.send_json_to(data)
        second_response = await communicator.receive_json_from()

        self.assertEqual(ProjectChatMessage.objects.count(), 1)
        self.assertEqual(
            first_response["content"]["message"]["id"],
            second_response["content"]["message"]["id"],
        )
        self.assertFalse(first_response["content"]["is_replay"])
        self.assertTrue(second_response["content"]["is_replay"])
        self.assertTrue(await recipient.receive_nothing())
        await communicator.disconnect()
        await recipient.disconnect()

    @skipUnlessDBFeature("has_select_for_update")
    def test_simultaneous_project_retries_keep_one_message_and_one_attachment(self):
        user_file = UserFile.objects.create(
            link="https://cdn.example.test/concurrent.pdf", user=self.member
        )
        client_message_id = uuid4()
        ready = Barrier(2)

        def send():
            try:
                ready.wait(timeout=10)
                return create_project_message(
                    chat_id=self.chat.pk,
                    author=self.member,
                    text="",
                    file_urls=[user_file.pk],
                    client_message_id=client_message_id,
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(send) for _ in range(2)]
            (first, first_created), (second, second_created) = [
                result.result(timeout=10) for result in results
            ]

        self.assertCountEqual([first_created, second_created], [True, False])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(ProjectChatMessage.objects.count(), 1)
        self.assertEqual(FileToMessage.objects.count(), 1)

    def test_failed_attachment_write_rolls_back_new_direct_chat_and_message(self):
        user_file = UserFile.objects.create(
            link="https://cdn.example.test/rollback.pdf", user=self.member
        )
        with (
            patch.object(FileToMessage.objects, "create", side_effect=IntegrityError),
            self.assertRaises(IntegrityError),
        ):
            create_direct_message(
                author=self.member,
                other_user=self.leader,
                text="",
                file_urls=[user_file.pk],
                client_message_id=uuid4(),
            )
        self.assertFalse(DirectChat.objects.exists())
        self.assertFalse(DirectChatMessage.objects.exists())
        self.assertFalse(FileToMessage.objects.exists())
