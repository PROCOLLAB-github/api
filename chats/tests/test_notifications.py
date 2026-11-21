from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from chats.models import ProgramChannel, ProjectChat
from chats.exceptions import MessageValidationException
from chats.notifications import should_notify
from chats.services.messages import create_project_message
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.tests.test_program_channels import create_program
from chats.tests.test_project_reads import create_project_chat
from projects.models import Collaborator


@override_settings(ALLOWED_HOSTS=["testserver"])
class ChatNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.manager = users.create(**TEST_USER1, is_staff=True, is_active=True)
        cls.member = users.create(**TEST_USER2, is_active=True)
        cls.outsider = users.create(**TEST_USER3, is_active=True)
        cls.project_chat = create_project_chat(cls.manager, cls.member)
        cls.program, cls.profile = create_program(cls.manager, cls.member)

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.member)

    def test_modes_are_personal_and_temporary_mute_expires(self):
        for kind, model, chat_id in (
            ("project-chat", ProjectChat, self.project_chat.pk),
            ("program-channel", ProgramChannel, self.program.pk),
        ):
            with self.subTest(kind=kind):
                url = reverse("chats:" + kind + "-notification-settings", args=[chat_id])
                clock = timezone.now()
                decision = dict(
                    author_id=self.manager.pk, mentioned_user_ids=[self.member.pk]
                )
                for mode, notify in (("mentions", True), ("muted", False), ("all", True)):
                    response = self.api.put(
                        url, {"mode": mode}, format="json", secure=True
                    )
                    self.assertEqual(response.json(), {"mode": mode, "muted_until": None})
                    self.assertIs(
                        should_notify(self.member, model, chat_id, **decision), notify
                    )
                with patch("chats.notifications.timezone.now", return_value=clock):
                    response = self.api.put(
                        url, {"mode": "mute_8h"}, format="json", secure=True
                    )
                    self.assertEqual(response.json()["mode"], "mute_8h")
                    self.assertFalse(
                        should_notify(self.member, model, chat_id, **decision)
                    )
                    self.assertTrue(
                        should_notify(
                            self.manager,
                            model,
                            chat_id,
                            author_id=self.member.pk,
                            mentioned_user_ids=[],
                        )
                    )
                with patch(
                    "chats.notifications.timezone.now",
                    return_value=clock + timedelta(hours=8),
                ):
                    self.assertEqual(
                        self.api.get(url, secure=True).json(),
                        {"mode": "all", "muted_until": None},
                    )
                    self.assertTrue(
                        should_notify(self.member, model, chat_id, **decision)
                    )

    def test_admin_sends_mentions_and_uses_same_personal_preference(self):
        self.client.force_login(self.manager)
        chat_id = self.project_chat.pk
        admin_name = "admin:chats_projectchat_message_search"
        settings_url = reverse(admin_name + "_notifications", args=[chat_id])
        self.assertContains(
            self.client.get(settings_url, secure=True), "Только упоминания"
        )
        self.assertEqual(
            self.client.post(settings_url, {"mode": "mentions"}, secure=True).status_code,
            302,
        )
        api_url = reverse("chats:project-chat-notification-settings", args=[chat_id])
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.api.get(api_url, secure=True).json()["mode"], "mentions")
        publish = reverse(admin_name + "_publish", args=[chat_id])
        response = self.client.post(
            publish,
            {
                "text": "Объявление",
                "mentions": [self.member.pk],
                "client_message_id": str(uuid4()),
            },
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.project_chat.messages.get().mentioned_user_ids, [self.member.pk]
        )
        recipients_url = reverse("chats:project-chat-mention-recipients", args=[chat_id])
        self.assertEqual(
            [
                user["id"]
                for user in self.api.get(recipients_url, secure=True).json()["results"]
            ],
            [self.member.pk],
        )
        Collaborator.objects.filter(project_id=chat_id, user=self.member).delete()
        self.api.force_authenticate(self.member)
        self.assertEqual(self.api.get(api_url, secure=True).status_code, 404)
        self.assertEqual(self.api.get(recipients_url, secure=True).status_code, 404)

    def test_project_message_cannot_mention_a_user_outside_the_chat(self):
        with self.assertRaises(MessageValidationException):
            create_project_message(
                chat_id=self.project_chat.pk,
                author=self.manager,
                text="Объявление",
                mentioned_user_ids=[self.outsider.pk],
            )
        self.assertFalse(self.project_chat.messages.exists())

    def test_channel_recipient_list_is_for_publishers(self):
        url = reverse("chats:program-channel-mention-recipients", args=[self.program.pk])
        self.assertEqual(self.api.get(url, secure=True).status_code, 403)
        self.api.force_authenticate(self.manager)
        self.assertEqual(
            [user["id"] for user in self.api.get(url, secure=True).json()["results"]],
            [self.member.pk],
        )
