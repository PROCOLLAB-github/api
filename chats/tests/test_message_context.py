from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from chats.models import DirectChat, ProjectChatMessageRead
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.tests.test_project_reads import create_project_chat


@override_settings(ALLOWED_HOSTS=["testserver"])
class MessageContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.author = users.create(**TEST_USER1)
        cls.member = users.create(
            **TEST_USER2, is_active=True, is_staff=True, is_superuser=True
        )
        cls.outsider = users.create(
            **TEST_USER3, is_active=True, is_staff=True, is_superuser=True
        )
        cls.direct = DirectChat.get_chat(cls.author, cls.member)
        cls.project = create_project_chat(cls.author, cls.member)
        cls.other_project = create_project_chat(cls.author, cls.member)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.member)

    def create_messages(self, chat):
        messages = [
            chat.messages.create(author=self.author, text=f"Сообщение {index}")
            for index in range(8)
        ]
        chat.messages.update(created_at=timezone.now())
        return messages

    def get_context(self, kind, message, **params):
        chat = getattr(self, kind)
        url = reverse(
            "chats:" + kind + "-chat-message-context", args=[chat.pk, message.pk]
        )
        return self.api.get(url, params, secure=True)

    def test_context_and_continuation_use_stable_boundaries(self):
        for kind in ("direct", "project"):
            with self.subTest(kind=kind):
                messages = self.create_messages(getattr(self, kind))
                messages[2].is_deleted = True
                messages[2].save(update_fields=["is_deleted"])
                response = self.get_context(kind, messages[4], limit=1)
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                data = response.json()
                self.assertEqual(
                    [item["id"] for item in data["results"]],
                    [messages[index].pk for index in (3, 4, 5)],
                )
                self.assertEqual(data["older_than"], messages[3].pk)
                self.assertEqual(data["newer_than"], messages[5].pk)

                # A deleted boundary can continue scrolling, but its content stays hidden.
                messages[3].is_deleted = True
                messages[3].save(update_fields=["is_deleted"])
                self.assertEqual(self.get_context(kind, messages[3]).status_code, 404)
                older = self.get_context(
                    kind, messages[3], direction="older", limit=2
                ).json()
                self.assertEqual(
                    [item["id"] for item in older["results"]],
                    [messages[index].pk for index in (0, 1)],
                )
                self.assertIsNone(older["older_than"])
                newer = self.get_context(
                    kind, messages[5], direction="newer", limit=2
                ).json()
                self.assertEqual(
                    [item["id"] for item in newer["results"]],
                    [messages[index].pk for index in (6, 7)],
                )
                self.assertIsNone(newer["newer_than"])
                self.assertEqual(
                    self.get_context(kind, messages[7], direction="newer").json(),
                    {"results": [], "older_than": None, "newer_than": None},
                )
        self.assertFalse(ProjectChatMessageRead.objects.exists())

    def test_context_rejects_nonmembers_foreign_anchors_and_invalid_options(self):
        message = self.project.messages.create(author=self.author, text="Проект")
        foreign = self.other_project.messages.create(
            author=self.author, text="Другой проект"
        )
        self.assertEqual(self.get_context("project", foreign).status_code, 404)
        for params in ({"limit": 0}, {"limit": 51}, {"direction": "invalid"}):
            self.assertEqual(
                self.get_context("project", message, **params).status_code, 400
            )
        self.api.force_authenticate(self.outsider)
        self.assertEqual(self.get_context("project", message).status_code, 404)

    def test_admin_can_open_the_search_hit_in_context(self):
        messages = self.create_messages(self.project)
        target = messages[4]
        self.client.force_login(self.member)
        search_url = reverse(
            "admin:chats_projectchat_message_search", args=[self.project.pk]
        )
        context_url = reverse(
            "admin:chats_projectchat_message_search_context",
            args=[self.project.pk, target.pk],
        )
        search = self.client.get(search_url, {"q": target.text}, secure=True)
        self.assertContains(search, context_url + "#selected-message")
        context = self.client.get(context_url, {"limit": 1}, secure=True)
        self.assertContains(context, 'id="selected-message"')
        for index in (3, 4, 5):
            self.assertContains(context, messages[index].text)
        self.assertNotContains(context, messages[2].text)
        self.assertContains(context, "direction=newer")
        self.assertContains(context, "direction=older")
        self.assertEqual(
            self.client.get(context_url, {"limit": 51}, secure=True).status_code, 400
        )
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(context_url, secure=True).status_code, 404)
