from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.urls import reverse
from rest_framework.test import APIClient

from chats.drafts import DraftConflict, save_draft
from chats.models import DirectChat
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.tests.test_program_channels import create_program
from chats.tests.test_project_reads import create_project_chat
from projects.models import Collaborator


@override_settings(ALLOWED_HOSTS=["testserver"])
class ChatDraftTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.author = users.create(**TEST_USER1, is_staff=True, is_active=True)
        cls.member = users.create(**TEST_USER2, is_active=True)
        cls.outsider = users.create(**TEST_USER3, is_active=True)
        cls.direct = DirectChat.get_chat(cls.author, cls.member)
        cls.project = create_project_chat(cls.author, cls.member)
        cls.program, _ = create_program(cls.author, cls.member)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.author)

    def put(self, url, text, revision):
        return self.api.put(
            url, {"text": text, "revision": revision}, format="json", secure=True
        )

    def test_drafts_are_private_and_list_exposes_only_the_marker(self):
        for kind, chat_id in (
            ("direct-chat", self.direct.pk),
            ("project-chat", self.project.pk),
            ("program-channel", self.program.pk),
        ):
            with self.subTest(kind=kind):
                route = "chats:" + kind
                url = reverse(route + "-draft", args=[chat_id])
                listing_url = reverse(route + "-list")
                self.api.force_authenticate(self.author)
                initial = self.api.get(url, secure=True)
                self.assertEqual(
                    initial.json(), {"text": "", "revision": 0, "updated_at": None}
                )
                self.assertIn("no-store", initial["Cache-Control"])
                written = self.put(url, "Мой черновик", 0)
                self.assertEqual(written.status_code, 200)
                self.assertEqual(written.json()["revision"], 1)
                self.assertEqual(self.api.get(url, secure=True).json(), written.json())
                listing = self.api.get(listing_url, secure=True)
                items = (
                    listing.json()["results"]
                    if kind == "program-channel"
                    else listing.json()
                )
                self.assertTrue(items[0]["has_draft"])
                self.assertNotContains(listing, "Мой черновик")

                self.api.force_authenticate(self.member)
                response = self.api.get(url, secure=True)
                if kind == "program-channel":
                    self.assertEqual(response.status_code, 403)
                else:
                    self.assertEqual(response.json()["text"], "")
                listing = self.api.get(listing_url, secure=True).json()
                items = listing["results"] if kind == "program-channel" else listing
                self.assertFalse(items[0]["has_draft"])
                self.api.force_authenticate(self.outsider)
                self.assertEqual(self.api.get(url, secure=True).status_code, 404)

    def test_clearing_draft_does_not_allow_an_older_write_to_restore_it(self):
        url = reverse("chats:direct-chat-draft", args=[self.direct.pk])
        first = self.put(url, "Старый текст", 0).json()
        self.assertEqual(self.put(url, "Старый текст", 0).json(), first)
        cleared = self.put(url, "", first["revision"]).json()
        conflict = self.put(url, "Отложенная правка", first["revision"])
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json(), cleared)
        self.assertEqual(self.api.get(url, secure=True).json()["text"], "")

    def test_admin_and_api_use_the_same_draft_version_and_channel_permission(self):
        self.client.force_login(self.author)
        admin_url = reverse(
            "admin:chats_programchannel_message_search_draft", args=[self.program.pk]
        )
        self.assertContains(self.client.get(admin_url, secure=True), "Личный черновик")
        response = self.client.post(
            admin_url, {"text": "Текст из админки", "revision": 0}, secure=True
        )
        self.assertEqual(response.status_code, 302)
        url = reverse("chats:program-channel-draft", args=[self.program.pk])
        self.assertEqual(
            self.api.get(url, secure=True).json()["text"], "Текст из админки"
        )
        publish_url = reverse(
            "admin:chats_programchannel_message_search_publish", args=[self.program.pk]
        )
        self.assertContains(self.client.get(publish_url, secure=True), "Текст из админки")
        second = self.put(url, "Правка с другого устройства", 1).json()
        for revision, text, expected_text in (
            (1, "Текст из админки", second["text"]),
            (second["revision"], second["text"], ""),
        ):
            response = self.client.post(
                publish_url,
                {
                    "text": text,
                    "draft_revision": revision,
                    "client_message_id": str(uuid4()),
                },
                secure=True,
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.api.get(url, secure=True).json()["text"], expected_text)
        self.program.managers.remove(self.author)
        self.assertEqual(self.client.get(admin_url, secure=True).status_code, 404)
        self.assertEqual(self.api.get(url, secure=True).status_code, 404)

    def test_removed_project_member_cannot_read_or_replace_saved_draft(self):
        self.api.force_authenticate(self.member)
        url = reverse("chats:project-chat-draft", args=[self.project.pk])
        self.assertEqual(self.put(url, "Черновик участника", 0).status_code, 200)
        Collaborator.objects.filter(project_id=self.project.pk, user=self.member).delete()
        self.assertEqual(self.api.get(url, secure=True).status_code, 404)
        self.assertEqual(self.put(url, "Правка", 1).status_code, 404)


class ChatDraftConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_only_one_device_can_commit_a_new_draft_at_the_same_revision(self):
        user = get_user_model().objects.create(**TEST_USER1)
        chat = DirectChat.get_chat(user, user)
        ready = Barrier(2)

        def write(text):
            try:
                ready.wait(timeout=10)
                return save_draft(user, DirectChat, chat.pk, text=text, revision=0)
            except DraftConflict as error:
                return error
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [
                pool.submit(write, text) for text in ("Первый текст", "Второй текст")
            ]
            results = [request.result(timeout=10) for request in requests]
        (saved,) = [result for result in results if isinstance(result, dict)]
        (conflict,) = [result for result in results if isinstance(result, DraftConflict)]
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(conflict.current, saved)
