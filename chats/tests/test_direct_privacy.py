from uuid import uuid4

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from chats.consumers import ChatConsumer
from chats.models import DirectChat, DirectChatSpamReport
from chats.services.messages import create_direct_message
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from projects.models import Collaborator, Project


@override_settings(ALLOWED_HOSTS=["testserver"])
class DirectPrivacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.sender = users.create(**TEST_USER1, is_active=True)
        cls.recipient = users.create(**TEST_USER2, is_active=True, is_staff=True)
        cls.outsider = users.create(**TEST_USER3, is_active=True, is_staff=True)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.recipient)
        self.chat_id = DirectChat.get_chat_id_from_users(self.sender, self.recipient)

    def url(self, suffix):
        return reverse("chats:direct-chat-" + suffix, args=[self.chat_id])

    def test_policy_is_private_and_applies_to_new_dialogs(self):
        privacy_url = reverse("chats:direct-chat-privacy")
        self.assertEqual(
            self.api.get(privacy_url, secure=True).json(), {"incoming": "everyone"}
        )
        self.client.force_login(self.recipient)
        settings_url = reverse("admin:chats_directchat_incoming_settings")
        self.assertContains(
            self.client.get(reverse("admin:chats_directchat_changelist"), secure=True),
            settings_url,
        )
        self.assertEqual(
            self.client.post(
                settings_url, {"incoming": "team_members"}, secure=True
            ).status_code,
            302,
        )
        self.assertEqual(
            self.api.get(privacy_url, secure=True).json(), {"incoming": "team_members"}
        )
        self.api.force_authenticate(self.sender)
        first = self.api.get(self.url("detail"), secure=True)
        self.assertFalse(first.json()["can_send"])
        project = Project.objects.create(leader=self.recipient)
        Collaborator.objects.create(project=project, user=self.sender)
        self.assertTrue(self.api.get(self.url("detail"), secure=True).json()["can_send"])
        create_direct_message(
            author=self.sender, other_user=self.recipient, text="Первое"
        )
        Collaborator.objects.filter(project=project, user=self.sender).delete()
        self.assertTrue(self.api.get(self.url("detail"), secure=True).json()["can_send"])
        self.assertEqual(
            self.api.get(privacy_url, secure=True).json(), {"incoming": "everyone"}
        )

    def test_report_and_block_use_shared_admin_rules_and_keep_history(self):
        message, _ = create_direct_message(
            author=self.sender, other_user=self.recipient, text="Входящее"
        )
        admin_url = reverse(
            "admin:chats_directchat_message_search_privacy", args=[self.chat_id]
        )
        self.client.force_login(self.recipient)
        self.assertContains(
            self.client.get(admin_url, secure=True), "Заблокировать собеседника"
        )
        response = self.client.post(admin_url, {"action": "block"}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.api.get(self.url("detail"), secure=True).json()["blocked_by_me"], True
        )
        payload = {"message_id": message["id"]}
        self.assertEqual(
            self.api.post(
                self.url("report-spam"), payload, format="json", secure=True
            ).status_code,
            204,
        )
        self.assertEqual(
            self.client.post(
                admin_url, {"action": "report", **payload}, secure=True
            ).status_code,
            302,
        )
        self.assertEqual(DirectChatSpamReport.objects.get().message_text, "Входящее")
        self.api.force_authenticate(self.sender)
        detail = self.api.get(self.url("detail"), secure=True).json()
        self.assertFalse(detail["blocked_by_me"])
        self.assertFalse(detail["can_send"])
        self.assertEqual(
            self.api.get(self.url("messages"), secure=True).json()["count"], 1
        )
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(admin_url, secure=True).status_code, 404)
        self.api.force_authenticate(self.recipient)
        response = self.api.put(
            self.url("block"), {"blocked": False}, format="json", secure=True
        )
        self.assertEqual(response.json(), {"blocked_by_me": False, "can_send": True})


class DirectPrivacySocketTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        self.sender = users.create(**TEST_USER1)
        self.recipient = users.create(**TEST_USER2)
        self.chat_id = DirectChat.get_chat_id_from_users(self.sender, self.recipient)

    async def test_socket_respects_privacy_and_keeps_acknowledged_retries_idempotent(
        self,
    ):
        from chats.direct_privacy import set_block, set_incoming_policy

        await database_sync_to_async(set_incoming_policy)(self.recipient, "team_members")
        socket = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        socket.scope["user"] = self.sender
        connected, _ = await socket.connect(timeout=5)
        self.assertTrue(connected)
        payload = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": self.chat_id,
                "text": "Сообщение",
                "client_message_id": str(uuid4()),
            },
        }
        try:
            await socket.send_json_to(payload)
            self.assertIn("error", await socket.receive_json_from())
            self.assertFalse(await DirectChat.objects.filter(pk=self.chat_id).aexists())
            await database_sync_to_async(set_incoming_policy)(self.recipient, "everyone")
            await socket.send_json_to(payload)
            first = (await socket.receive_json_from())["content"]["message"]
            await database_sync_to_async(set_block)(self.recipient, self.sender, True)
            await socket.send_json_to(payload)
            replay = (await socket.receive_json_from())["content"]
            self.assertTrue(replay["is_replay"])
            self.assertEqual(replay["message"]["id"], first["id"])
            payload["content"]["client_message_id"] = str(uuid4())
            await socket.send_json_to(payload)
            self.assertIn("error", await socket.receive_json_from())
            payload["type"] = "user_typing"
            await socket.send_json_to(payload)
            self.assertIn("error", await socket.receive_json_from())
            payload["type"] = "edit_message"
            payload["content"]["message_id"] = first["id"]
            payload["content"]["text"] = "Измененный текст"
            await socket.send_json_to(payload)
            self.assertIn("error", await socket.receive_json_from())
        finally:
            await socket.disconnect()
