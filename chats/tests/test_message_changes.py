from uuid import uuid4

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from chats.consumers import ChatConsumer
from chats.models import DirectChat, ProjectChatMessageRead
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.tests.test_project_reads import create_project_chat
from projects.models import Collaborator


def chat_url(kind, chat, suffix):
    name = f"{kind}-chat-{suffix}"
    return reverse("chats:" + name, args=[chat.pk])


@override_settings(ALLOWED_HOSTS=["testserver"])
class MessageChangesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.author = users.create(**TEST_USER1)
        cls.member = users.create(**TEST_USER2)
        cls.outsider = users.create(**TEST_USER3)
        cls.direct = DirectChat.get_chat(cls.author, cls.member)
        cls.project = create_project_chat(cls.author, cls.member)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.member)

    def changes(self, kind, chat, **params):
        return self.api.get(chat_url(kind, chat, "message-changes"), params, secure=True)

    def test_pages_include_current_state_and_personal_project_reads(self):
        for kind in ("direct", "project"):
            with self.subTest(kind=kind):
                chat = getattr(self, kind)
                old = chat.messages.create(author=self.author, text="История")
                deleted = chat.messages.create(author=self.author, text="Будет удалено")
                history = self.api.get(chat_url(kind, chat, "messages"), secure=True)
                cursor = history.json()["sync_cursor"]

                new = chat.messages.create(author=self.author, text="Новое")
                if kind == "project":
                    ProjectChatMessageRead.objects.create(message=new, user=self.member)
                old.text = "Исправленная история"
                old.save(update_fields=["text"])
                deleted.is_deleted = True
                deleted.save(update_fields=["is_deleted"])

                first = self.changes(kind, chat, after=cursor, limit=2)
                self.assertEqual(first.status_code, 200)
                self.assertIn("no-store", first["Cache-Control"])
                page = first.json()
                self.assertTrue(page["has_more"])
                self.assertEqual(
                    [item["message_id"] for item in page["results"]], [new.pk, old.pk]
                )
                self.assertEqual(
                    page["results"][0]["message"]["is_read"], kind == "project"
                )
                self.assertEqual(
                    page["results"][1]["message"]["text"], "Исправленная история"
                )
                final = self.changes(kind, chat, after=page["next_cursor"]).json()
                self.assertEqual(
                    final["results"], [{"type": "delete", "message_id": deleted.pk}]
                )
                self.assertFalse(final["has_more"])
                self.assertEqual(
                    self.changes(kind, chat, after=final["next_cursor"]).json(),
                    {
                        "results": [],
                        "next_cursor": final["next_cursor"],
                        "has_more": False,
                    },
                )
        self.assertEqual(ProjectChatMessageRead.objects.count(), 1)

    def test_validation_and_project_membership_use_current_state(self):
        for kind in ("direct", "project"):
            chat = getattr(self, kind)
            with self.subTest(kind=kind):
                self.api.force_authenticate(self.member)
                for params in ({}, {"after": -1}, {"after": 0, "limit": 101}):
                    self.assertEqual(self.changes(kind, chat, **params).status_code, 400)
                self.assertEqual(self.changes(kind, chat, after=1).status_code, 409)
                self.api.force_authenticate(self.outsider)
                self.assertEqual(self.changes(kind, chat, after=0).status_code, 404)
        Collaborator.objects.filter(project_id=self.project.pk, user=self.member).delete()
        self.api.force_authenticate(self.member)
        self.assertEqual(self.changes("project", self.project, after=0).status_code, 404)

    def test_saving_chat_metadata_preserves_cursor(self):
        stale = DirectChat.objects.get(pk=self.direct.pk)
        self.direct.messages.create(author=self.author, text="Новое")
        stale.save()
        self.assertEqual(
            self.changes("direct", self.direct, after=0).json()["next_cursor"], 1
        )

    def test_admin_organizer_edits_and_deletes_own_message(self):
        self.author.is_staff = True
        self.author.is_active = True
        self.author.save(update_fields=["is_staff", "is_active"])
        self.author.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="chats", codename="view_projectchat"
            )
        )
        self.client.force_login(self.author)
        own = self.project.messages.create(author=self.author, text="До правки")
        other = self.project.messages.create(author=self.member, text="Чужое сообщение")
        route = "admin:chats_projectchat_message_search_change"
        own_url = reverse(route, args=[self.project.pk, own.pk])
        other_url = reverse(route, args=[self.project.pk, other.pk])
        history = self.api.get(chat_url("project", self.project, "messages"), secure=True)
        cursor = history.json()["sync_cursor"]
        self.assertContains(self.client.get(own_url, secure=True), "До правки")
        self.assertEqual(self.client.get(other_url, secure=True).status_code, 404)
        invalid = self.client.post(own_url, {"action": "edit", "text": ""}, secure=True)
        self.assertContains(invalid, "Сообщение не может быть пустым.", status_code=400)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                own_url, {"action": "edit", "text": "После правки"}, secure=True
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(callbacks), 1)
        changed = self.changes("project", self.project, after=cursor).json()
        self.assertEqual(changed["results"][0]["message"]["text"], "После правки")
        self.assertEqual(
            self.client.post(own_url, {"action": "delete"}, secure=True).status_code, 302
        )
        removed = self.changes(
            "project", self.project, after=changed["next_cursor"]
        ).json()
        self.assertEqual(removed["results"], [{"type": "delete", "message_id": own.pk}])


@override_settings(ALLOWED_HOSTS=["testserver"])
class ReconnectTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        self.author = users.create(**TEST_USER1)
        self.member = users.create(**TEST_USER2)
        self.chat = create_project_chat(self.author, self.member)
        self.old = self.chat.messages.create(author=self.author, text="Первое")
        self.api = APIClient()
        self.api.force_authenticate(self.member)

    async def test_disconnected_member_can_recover_websocket_writes(self):
        history = await database_sync_to_async(self.api.get)(
            chat_url("project", self.chat, "messages"), secure=True
        )
        cursor = history.json()["sync_cursor"]
        writer = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        writer.scope["user"] = self.author
        connected, _ = await writer.connect(timeout=5)
        self.assertTrue(connected)

        async def send(kind, **content):
            await writer.send_json_to(
                {
                    "type": kind,
                    "content": {
                        "chat_type": "project",
                        "chat_id": self.chat.pk,
                        **content,
                    },
                }
            )
            response = await writer.receive_json_from(timeout=5)
            self.assertEqual(response["type"], kind)
            return response["content"]

        try:
            send_params = {"text": "Новое", "client_message_id": str(uuid4())}
            new = await send("new_message", **send_params)
            replay = await send("new_message", **send_params)
            self.assertTrue(replay["is_replay"])
            await send("edit_message", message_id=self.old.pk, text="Правка")
            await send("delete_message", message_id=new["message"]["id"])
        finally:
            await writer.disconnect()

        changes = await database_sync_to_async(self.api.get)(
            chat_url("project", self.chat, "message-changes"),
            {"after": cursor},
            secure=True,
        )
        self.assertEqual(changes.status_code, 200)
        data = changes.json()
        edited, removed = data["results"]
        self.assertEqual(edited["message"]["text"], "Правка")
        self.assertEqual(removed, {"type": "delete", "message_id": new["message"]["id"]})
        self.assertEqual(data["next_cursor"], cursor + 3)
