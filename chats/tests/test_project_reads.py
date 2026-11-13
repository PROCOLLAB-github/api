from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from chats.consumers import ChatConsumer
from chats.models import ProjectChat, ProjectChatMessage, ProjectChatMessageRead
from chats.project_reads import mark_project_message_read
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from projects.models import Collaborator, Project


def create_project_chat(leader, *members):
    project = Project.objects.create(leader=leader)
    chat, _ = ProjectChat.objects.get_or_create(
        pk=project.pk, defaults={"project": project}
    )
    for member in members:
        Collaborator.objects.create(project=project, user=member, role="User")
    return chat


@override_settings(ALLOWED_HOSTS=["testserver"])
class ProjectReadsAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.leader = users.create(**TEST_USER1)
        cls.reader = users.create(
            **TEST_USER2, is_staff=True, is_superuser=True, is_active=True
        )
        cls.other_reader = users.create(**TEST_USER3)
        cls.chat = create_project_chat(cls.leader, cls.reader, cls.other_reader)

    def setUp(self):
        self.api = APIClient()

    def get(self, user, route, **kwargs):
        self.api.force_authenticate(user=user)
        url = reverse("chats:" + route, kwargs=kwargs)
        response = self.api.get(url, secure=True)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def create_message(self, **overrides):
        return ProjectChatMessage.objects.create(
            **(
                {"chat": self.chat, "author": self.leader, "text": "Сообщение"}
                | overrides
            )
        )

    def test_list_detail_and_global_indicator_use_the_same_personal_unreads(self):
        first = self.create_message()
        latest = self.create_message()
        self.create_message(is_read=True)
        self.create_message(is_deleted=True)
        self.create_message(author=self.reader)
        mark_project_message_read(
            chat_id=self.chat.pk, message_id=latest.pk, user=self.reader
        )

        detail = self.get(self.reader, "project-chat-detail", pk=self.chat.pk)
        item = self.get(self.reader, "project-chat-list")[0]
        for data in (detail, item):
            self.assertEqual(data["unread_count"], 1)
            self.assertEqual(data["first_unread_message_id"], first.pk)
        self.assertTrue(self.get(self.reader, "has-chat-unreads")["has_unreads"])
        other_detail = self.get(self.other_reader, "project-chat-detail", pk=self.chat.pk)
        self.assertEqual(other_detail["unread_count"], 3)
        self.assertEqual(other_detail["first_unread_message_id"], first.pk)

        mark_project_message_read(
            chat_id=self.chat.pk, message_id=first.pk, user=self.reader
        )
        detail = self.get(self.reader, "project-chat-detail", pk=self.chat.pk)
        self.assertEqual(detail["unread_count"], 0)
        self.assertIsNone(detail["first_unread_message_id"])
        self.assertFalse(self.get(self.reader, "has-chat-unreads")["has_unreads"])
        self.assertTrue(self.get(self.other_reader, "has-chat-unreads")["has_unreads"])

    def test_history_personalizes_read_flag_for_messages_and_replies(self):
        original = self.create_message()
        reply = self.create_message(reply_to=original)
        mark_project_message_read(
            chat_id=self.chat.pk, message_id=original.pk, user=self.reader
        )

        for user, is_read in (
            (self.leader, True),
            (self.reader, True),
            (self.other_reader, False),
        ):
            with self.subTest(user=user.pk):
                data = self.get(user, "project-chat-messages", id=self.chat.pk)
                by_id = {message["id"]: message for message in data["results"]}
                self.assertFalse(by_id[reply.pk]["is_read"])
                for item in (by_id[original.pk], by_id[reply.pk]["reply_to"]):
                    self.assertIs(item["is_read"], is_read)
                    self.assertEqual(item["read_count"], 1)

    def test_admin_marks_only_for_the_current_project_member(self):
        message = self.create_message()
        self.client.force_login(self.reader)
        url = reverse("admin:chats_projectchatmessage_changelist")
        form = {"action": "mark_read_for_me", "_selected_action": [message.pk]}
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(url, form, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(callbacks), 1)
        self.assertTrue(
            ProjectChatMessageRead.objects.filter(
                message=message, user=self.reader
            ).exists()
        )

        Collaborator.objects.filter(project=self.chat.project, user=self.reader).delete()
        another = self.create_message()
        response = self.client.post(
            url, {**form, "_selected_action": [another.pk]}, secure=True
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectChatMessageRead.objects.filter(message=another).exists())


class ProjectReadEventsTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        self.author = users.create(**TEST_USER1)
        self.reader = users.create(**TEST_USER2)
        self.other_reader = users.create(**TEST_USER3)
        self.chat = create_project_chat(self.author, self.reader, self.other_reader)
        self.message = ProjectChatMessage.objects.create(
            chat=self.chat, author=self.author, text="Сообщение"
        )

    async def connect(self, user):
        socket = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        socket.scope["user"] = user
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        return socket

    async def receive_chat_event(self, socket):
        while True:
            response = await socket.receive_json_from()
            if response.get("type") not in {"set_online", "set_offline"}:
                return response

    def event(self, event_type="message_read", **overrides):
        return {
            "type": event_type,
            "content": {
                "chat_type": "project",
                "chat_id": str(self.chat.pk),
                "message_id": self.message.pk,
                **overrides,
            },
        }

    @override_settings(RUNNING_TESTS=False)
    async def test_read_events_and_edits_preserve_the_other_members_unread_state(self):
        author = await self.connect(self.author)
        reader = await self.connect(self.reader)
        other = await self.connect(self.other_reader)
        try:
            await reader.send_json_to(self.event())
            receipt = await self.receive_chat_event(reader)
            self.assertEqual(receipt, await self.receive_chat_event(author))
            self.assertEqual(receipt["content"]["read_count"], 1)
            self.assertTrue(await other.receive_nothing())

            await reader.send_json_to(self.event())
            self.assertEqual(await self.receive_chat_event(reader), receipt)
            self.assertTrue(await author.receive_nothing())

            await author.send_json_to(self.event("edit_message", text="Исправлено"))
            for socket, expected in ((author, True), (reader, True), (other, False)):
                edit = await self.receive_chat_event(socket)
                self.assertEqual(edit["type"], "edit_message")
                self.assertIs(edit["content"]["message"]["is_read"], expected)
                self.assertEqual(edit["content"]["message"]["read_count"], 1)
        finally:
            await other.disconnect()
            await reader.disconnect()
            await author.disconnect()
        self.assertEqual(ProjectChatMessageRead.objects.count(), 1)

    async def test_read_rejects_deleted_messages_and_messages_from_another_chat(self):
        another = create_project_chat(self.author, self.reader)
        deleted = ProjectChatMessage.objects.create(
            chat=self.chat, author=self.author, text="Удалено", is_deleted=True
        )
        socket = await self.connect(self.reader)
        try:
            for event in (
                self.event(chat_id=str(another.pk)),
                self.event(message_id=deleted.pk),
            ):
                await socket.send_json_to(event)
                self.assertIn("error", await self.receive_chat_event(socket))
        finally:
            await socket.disconnect()
        self.assertFalse(ProjectChatMessageRead.objects.exists())

    async def test_author_read_does_not_create_a_receipt_or_notify_members(self):
        author = await self.connect(self.author)
        try:
            await author.send_json_to(self.event())
            self.assertTrue(await author.receive_nothing())
        finally:
            await author.disconnect()
        self.assertFalse(ProjectChatMessageRead.objects.exists())
