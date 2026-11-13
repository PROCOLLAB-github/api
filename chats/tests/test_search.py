from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from chats.models import DirectChat, DirectChatMessage, FileToMessage, ProjectChatMessage
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.tests.test_project_reads import create_project_chat
from files.models import UserFile


@override_settings(ALLOWED_HOSTS=["testserver"])
class ChatSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.member = users.create(
            **TEST_USER1, is_staff=True, is_superuser=True, is_active=True
        )
        cls.author = users.create(**TEST_USER2)
        cls.outsider = users.create(
            **TEST_USER3, is_staff=True, is_superuser=True, is_active=True
        )
        cls.direct = DirectChat.get_chat(cls.member, cls.author)
        cls.project = create_project_chat(cls.author, cls.member)

        for kind, model, chat in (
            ("direct", DirectChatMessage, cls.direct),
            ("project", ProjectChatMessage, cls.project),
        ):
            cls.make_messages(kind, model, chat)

    @classmethod
    def make_messages(cls, kind, model, chat):
        attachments_message = model.objects.create(
            chat=chat, author=cls.author, text="Материалы по проекту"
        )
        text_message = model.objects.create(
            chat=chat, author=cls.member, text="Обсудим План"
        )
        deleted = model.objects.create(
            chat=chat, author=cls.author, text="Удаленный План", is_deleted=True
        )
        model.objects.filter(pk=text_message.pk).update(reply_to=deleted)
        for index, message in enumerate(
            (attachments_message, attachments_message, deleted)
        ):
            file = UserFile.objects.create(
                link="https://cdn.example.test/{}-{}.pdf".format(kind, index),
                user=cls.author,
                name="План",
                extension="pdf",
            )
            FileToMessage.objects.create(file=file, **{f"{kind}_message": message})

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.member)

    def search(self, kind, **params):
        chat = getattr(self, kind)
        return self.api.get(
            reverse("chats:" + kind + "-chat-messages", args=[chat.pk]),
            params,
            secure=True,
        )

    def test_search_scopes_author_filter_and_pagination(self):
        for kind in ("direct", "project"):
            with self.subTest(chat=kind):
                response = self.search(kind, q=" план ", limit=1)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["count"], 2)
                self.assertIsNotNone(data["next"])
                self.assertEqual(data["results"][0]["text"], "Обсудим План")
                self.assertIsNone(data["results"][0]["reply_to"])

                files = self.search(kind, q="план.PDF", scope="files").json()
                self.assertEqual(files["count"], 1)
                self.assertEqual(len(files["results"][0]["files"]), 2)
                text = self.search(kind, q="ПЛАН", scope="messages").json()
                self.assertEqual(text["count"], 1)
                by_author = self.search(kind, author_id=self.author.pk).json()
                self.assertEqual(by_author["count"], 1)
                self.assertEqual(by_author["results"][0]["text"], "Материалы по проекту")
                self.assertEqual(self.search(kind, q="План.*").json()["count"], 0)

    def test_invalid_filters_return_400_and_a_nonmember_cannot_search(self):
        for params in ({"author_id": "-1"}, {"q": "x" * 201}, {"scope": "unknown"}):
            with self.subTest(params=params):
                self.assertEqual(self.search("project", **params).status_code, 400)
        self.api.force_authenticate(self.outsider)
        self.assertEqual(self.search("project", q="План").status_code, 403)
        self.assertEqual(self.search("direct", q="План").status_code, 403)

    def test_admin_uses_same_search_and_restricts_access_to_chat_members(self):
        self.client.force_login(self.member)
        url = reverse("admin:chats_projectchat_message_search", args=[self.project.pk])
        response = self.client.get(url, {"q": "план.PDF", "scope": "files"}, secure=True)
        self.assertContains(response, "Материалы по проекту")
        self.assertNotContains(response, "Обсудим План")
        self.assertNotContains(response, "Удаленный План")
        self.assertContains(response, "Найдено сообщений: 1")

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url, secure=True).status_code, 404)
