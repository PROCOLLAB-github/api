from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework_simplejwt.tokens import AccessToken

from chats.models import DirectChat, ProjectChat
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.tests.test_project_reads import create_project_chat
from chats.views import ProjectChatDetail
from projects.models import Collaborator, Project
from procollab.asgi import application


@override_settings(ALLOWED_HOSTS=["testserver", "dev.procollab.ru", "127.0.0.1"])
class ChatPermissionsTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.leader = get_user_model().objects.create(**TEST_USER1)
        self.collaborator = get_user_model().objects.create(**TEST_USER2)
        self.outsider = get_user_model().objects.create(**TEST_USER3)
        self.project = Project.objects.create(leader=self.leader)
        self.chat = ProjectChat.objects.create(project=self.project)
        Collaborator.objects.create(
            user=self.collaborator,
            project=self.project,
            role="User",
        )

        self.staff = get_user_model().objects.create(
            email="swagger-staff@test.test",
            password="very_strong_password",
            first_name="Swagger",
            last_name="Staff",
            birthday="2000-01-01",
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )
        self.staff.set_password("very_strong_password")
        self.staff.save()

    def test_swagger_schema_is_available_for_staff(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            "/swagger/?format=openapi",
            secure=True,
            HTTP_HOST="dev.procollab.ru",
        )

        self.assertEqual(response.status_code, 200)

    def test_project_chat_detail_is_available_for_leader(self):
        request = self.factory.get(f"/chats/projects/{self.chat.id}/")
        force_authenticate(request, user=self.leader)

        response = ProjectChatDetail.as_view()(request, pk=self.chat.id)

        self.assertEqual(response.status_code, 200)

    def test_project_chat_detail_is_available_for_collaborator(self):
        request = self.factory.get(f"/chats/projects/{self.chat.id}/")
        force_authenticate(request, user=self.collaborator)

        response = ProjectChatDetail.as_view()(request, pk=self.chat.id)

        self.assertEqual(response.status_code, 200)

    def test_project_chat_detail_is_forbidden_for_outsider(self):
        request = self.factory.get(f"/chats/projects/{self.chat.id}/")
        force_authenticate(request, user=self.outsider)

        response = ProjectChatDetail.as_view()(request, pk=self.chat.id)

        self.assertEqual(response.status_code, 403)

    def test_direct_chat_preview_and_unreads_use_visible_incoming_messages(self):
        chat = DirectChat.get_chat(self.leader, self.collaborator)
        chat.messages.create(author=self.leader, text="Свое сообщение")
        unread = chat.messages.create(author=self.collaborator, text="Новое сообщение")
        chat.messages.create(
            author=self.collaborator, text="Удаленное сообщение", is_deleted=True
        )
        api = APIClient()
        api.force_authenticate(self.leader)
        listing_url = reverse("chats:direct-chat-list")
        unreads_url = reverse("chats:has-chat-unreads")

        preview = api.get(listing_url, secure=True).json()[0]["last_message"]
        self.assertEqual(preview["id"], unread.pk)
        self.assertTrue(api.get(unreads_url, secure=True).json()["has_unreads"])
        unread.is_deleted = True
        unread.save(update_fields=["is_deleted"])
        preview = api.get(listing_url, secure=True).json()[0]["last_message"]
        self.assertEqual(preview["text"], "Свое сообщение")
        self.assertFalse(api.get(unreads_url, secure=True).json()["has_unreads"])


@override_settings(RUNNING_TESTS=False)
class ChatSocketAccessTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        self.leader = users.create(**TEST_USER1, is_active=True)
        self.member = users.create(**TEST_USER2, is_active=True)
        self.chat = create_project_chat(self.leader, self.member)
        Collaborator.objects.filter(project_id=self.chat.pk, user=self.leader).delete()

    def open_chat(self, user):
        return WebsocketCommunicator(
            application,
            "/ws/chat/",
            subprotocols=["Bearer", str(AccessToken.for_user(user))],
        )

    async def receive_chat_event(self, socket):
        while True:
            event = await socket.receive_json_from(timeout=5)
            if event.get("type") not in {"set_online", "set_offline"}:
                return event

    async def send_project_message(self, socket, text):
        await socket.send_json_to(
            {
                "type": "new_message",
                "content": {
                    "chat_type": "project",
                    "chat_id": self.chat.pk,
                    "text": text,
                },
            }
        )

    async def test_leader_receives_updates_and_removed_member_stops_receiving_them(self):
        leader = self.open_chat(self.leader)
        member = self.open_chat(self.member)
        self.assertEqual(await leader.connect(), (True, "Bearer"))
        self.assertEqual(await member.connect(), (True, "Bearer"))
        try:
            await self.send_project_message(member, "Первое сообщение")
            self.assertEqual(
                (await self.receive_chat_event(leader))["content"]["message"]["text"],
                "Первое сообщение",
            )
            self.assertEqual(
                (await self.receive_chat_event(member))["type"], "new_message"
            )
            await database_sync_to_async(
                Collaborator.objects.filter(
                    project_id=self.chat.pk, user=self.member
                ).delete
            )()
            await self.send_project_message(leader, "Сообщение после изменения состава")
            self.assertEqual(
                (await self.receive_chat_event(leader))["type"], "new_message"
            )
            self.assertTrue(await member.receive_nothing())
        finally:
            await member.disconnect()
            await leader.disconnect()

    async def test_inactive_account_cannot_open_chat_socket(self):
        await database_sync_to_async(
            get_user_model().objects.filter(pk=self.member.pk).update
        )(is_active=False)
        socket = self.open_chat(self.member)
        connected, _ = await socket.connect()
        self.assertFalse(connected)
        await socket.disconnect()

    async def test_connection_stays_available_after_invalid_event(self):
        socket = self.open_chat(self.leader)
        self.assertEqual(await socket.connect(), (True, "Bearer"))
        try:
            await socket.send_to(text_data="{")
            self.assertIn("error", await self.receive_chat_event(socket))
            await self.send_project_message(socket, "Сообщение проекта")
            self.assertEqual(
                (await self.receive_chat_event(socket))["type"], "new_message"
            )
        finally:
            await socket.disconnect()
