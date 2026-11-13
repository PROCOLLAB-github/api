from unittest.mock import patch
from uuid import uuid4

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from chats.models import ProgramChannel
from chats.notifications import set_notification_mode
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.tests.test_attachment_download import STORAGE, upstream_file
from files.models import UserFile
from files.typings import FileInfo
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from procollab.asgi import application


def create_program(manager, member):
    now = timezone.now()
    program = PartnerProgram.objects.create(
        name="Программа",
        draft=False,
        datetime_started=now,
        datetime_registration_ends=now,
        datetime_finished=now,
    )
    program.managers.add(manager)
    profile = PartnerProgramUserProfile.objects.create(
        partner_program=program, user=member, partner_program_data={}
    )
    return program, profile


@override_settings(ALLOWED_HOSTS=["testserver"], SELECTEL_SWIFT_URL=STORAGE)
class ProgramChannelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.manager = users.create(**TEST_USER1, is_staff=True, is_active=True)
        cls.member = users.create(**TEST_USER2, is_active=True)
        cls.outsider = users.create(**TEST_USER3, is_staff=True, is_active=True)
        cls.program, cls.profile = create_program(cls.manager, cls.member)
        cls.channel = ProgramChannel.objects.get(pk=cls.program.pk)
        cls.file = UserFile.objects.create(
            link=STORAGE + "program.pdf",
            user=cls.manager,
            name="План программы",
            extension="pdf",
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.manager)
        self.history = self.url("messages")

    def url(self, suffix, *extra):
        return reverse("chats:program-channel-" + suffix, args=[self.channel.pk, *extra])

    def publish(self, text="Анонс", **payload):
        return self.api.post(
            self.history, {"text": text, **payload}, format="json", secure=True
        )

    def list_channels(self):
        url = reverse("chats:program-channel-list")
        return self.api.get(url, secure=True).json()["results"]

    def test_permissions_and_protected_attachment_follow_current_membership(self):
        self.api.force_authenticate(self.member)
        self.assertEqual(self.publish().status_code, 403)
        self.assertFalse(self.list_channels()[0]["can_publish"])
        self.api.force_authenticate(self.manager)
        self.assertTrue(self.list_channels()[0]["can_publish"])
        publication = self.publish(file_urls=[self.file.pk]).json()
        link = publication["files"][0]["link"]
        self.assertNotIn(STORAGE, link)

        self.api.force_authenticate(self.member)
        summary = self.api.get(self.url("detail"), secure=True).json()
        self.assertEqual(summary["last_message"]["id"], publication["id"])
        result = self.api.get(
            self.history, {"q": "план программы", "scope": "files"}, secure=True
        ).json()
        self.assertEqual([item["id"] for item in result["results"]], [publication["id"]])
        context = self.api.get(
            self.url("message-context", publication["id"]), secure=True
        ).json()
        self.assertEqual(context["results"][0]["id"], publication["id"])
        self.assertEqual(
            self.api.get(self.url("files"), secure=True).json()[0]["link"], link
        )
        with (
            patch(
                "files.downloads.SelectelSwiftStorage._get_auth_token",
                return_value="test",
            ),
            patch(
                "files.downloads.requests.get", return_value=upstream_file()
            ) as storage,
        ):
            response = self.api.get(link, secure=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"abcdef")
            self.profile.delete()
            self.assertEqual(self.api.get(self.history, secure=True).status_code, 404)
            self.assertEqual(self.api.get(link, secure=True).status_code, 404)
            self.assertEqual(self.list_channels(), [])
            storage.assert_called_once()
        self.api.force_authenticate(self.outsider)
        self.assertEqual(self.publish().status_code, 404)

    def test_read_cursor_is_personal_and_publication_retries_keep_same_id(self):
        key = str(uuid4())
        first = self.publish(client_message_id=key, file_urls=[self.file.pk])
        self.assertEqual(first.status_code, 201)
        replay = self.publish(client_message_id=key, file_urls=[self.file.pk])
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.json(), replay.json())
        second = self.publish("Вторая публикация").json()["id"]
        self.assertEqual(self.list_channels()[0]["unread_count"], 0)

        self.api.force_authenticate(self.member)
        listing = self.list_channels()[0]
        self.assertEqual(listing["unread_count"], 2)
        self.assertEqual(listing["first_unread_message_id"], first.json()["id"])
        for message_id in (second, first.json()["id"]):
            read = self.api.post(
                self.url("read"), {"message_id": message_id}, format="json", secure=True
            )
            self.assertEqual(read.json(), {"last_message_id": second})
        self.assertEqual(self.list_channels()[0]["unread_count"], 0)
        self.assertIsNone(self.list_channels()[0]["first_unread_message_id"])

    def test_edit_and_delete_are_visible_in_sync_and_withdraw_attachment(self):
        published = self.publish(file_urls=[self.file.pk]).json()
        message_id = published["id"]
        change = self.url("message-change", message_id)
        cursor = self.api.get(self.history, secure=True).json()["sync_cursor"]
        self.assertEqual(
            self.api.patch(
                change, {"text": "Правка"}, format="json", secure=True
            ).status_code,
            200,
        )
        changes = self.url("message-changes")
        delta = self.api.get(changes, {"after": cursor}, secure=True).json()
        self.assertEqual(delta["results"][0]["message"]["text"], "Правка")
        self.assertEqual(self.api.delete(change, secure=True).status_code, 204)
        self.api.force_authenticate(self.member)
        deleted = self.api.get(
            changes, {"after": delta["next_cursor"]}, secure=True
        ).json()
        self.assertEqual(
            deleted["results"], [{"type": "delete", "message_id": message_id}]
        )
        self.assertEqual(
            self.api.get(published["files"][0]["link"], secure=True).status_code, 404
        )

    def test_manager_can_publish_and_edit_in_admin_with_shared_validation(self):
        self.client.force_login(self.manager)
        name = "admin:chats_programchannel_message_search"
        search_url = reverse(name, args=[self.channel.pk])
        publish_url = reverse(name + "_publish", args=[self.channel.pk])
        self.assertContains(self.client.get(search_url, secure=True), publish_url)
        uploaded_url = STORAGE + "admin.txt"
        with patch(
            "chats.admin.ProgramChannelAdmin.cdn.upload",
            return_value=FileInfo(
                url=uploaded_url,
                name="Объявление",
                extension="txt",
                mime_type="text/plain",
                detected_mime_type="text/plain",
                size=5,
            ),
        ):
            upload_response = self.client.post(
                publish_url,
                {"action": "upload", "file": SimpleUploadedFile("note.txt", b"hello")},
                secure=True,
            )
        self.assertContains(upload_response, "Файл загружен и выбран для публикации.")
        self.assertTrue(
            UserFile.objects.filter(pk=uploaded_url, user=self.manager).exists()
        )
        payload = {
            "text": "",
            "files": [uploaded_url],
            "client_message_id": str(uuid4()),
        }
        for _ in range(2):
            response = self.client.post(publish_url, payload, secure=True)
            self.assertEqual(response.status_code, 302)
        message = self.channel.messages.get()
        change_url = reverse(name + "_change", args=[self.channel.pk, message.pk])
        response = self.client.post(
            change_url, {"action": "edit", "text": "Изменено в админке"}, secure=True
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.api.get(self.history, secure=True).json()["results"][0]["text"],
            "Изменено в админке",
        )
        self.program.managers.remove(self.manager)
        self.assertEqual(self.client.get(search_url, secure=True).status_code, 404)

    def test_program_return_to_draft_hides_channel_without_losing_history(self):
        self.assertEqual(self.publish().status_code, 201)
        PartnerProgram.objects.filter(pk=self.program.pk).update(draft=True)
        self.assertEqual(self.api.get(self.history, secure=True).status_code, 404)
        self.assertEqual(self.list_channels(), [])
        PartnerProgram.objects.filter(pk=self.program.pk).update(draft=False)
        self.assertEqual(self.api.get(self.history, secure=True).json()["count"], 1)

    @patch("files.service.requests.put")
    @patch("files.service.SelectelSwiftStorage._get_auth_token", return_value="test")
    def test_failed_storage_upload_does_not_create_an_attachment(self, _token, put):
        put.return_value.status_code = 503
        before = UserFile.objects.count()
        response = self.api.post(
            "/files/?preserve_original=true",
            {"file": SimpleUploadedFile("note.txt", b"hello")},
            secure=True,
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(UserFile.objects.count(), before)


@override_settings(ALLOWED_HOSTS=["testserver"], RUNNING_TESTS=False)
class ProgramChannelSocketTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        self.manager = users.create(**TEST_USER1, is_active=True)
        self.member = users.create(**TEST_USER2, is_active=True)
        self.program, self.profile = create_program(self.manager, self.member)

    async def test_channel_change_is_delivered_only_while_member_has_access(self):
        socket = WebsocketCommunicator(
            application,
            "/ws/chat/",
            subprotocols=["Bearer", str(AccessToken.for_user(self.member))],
        )
        api = APIClient()
        api.force_authenticate(self.manager)
        url = reverse("chats:program-channel-messages", args=[self.program.pk])
        self.assertEqual(await socket.connect(), (True, "Bearer"))
        try:
            await socket.send_json_to(
                {
                    "type": "subscribe_program_channel",
                    "content": {"channel_id": self.program.pk},
                }
            )
            self.assertEqual(
                (await socket.receive_json_from(timeout=5))["type"],
                "subscribe_program_channel",
            )
            response = await database_sync_to_async(api.post)(
                url, {"text": "Публикация"}, format="json", secure=True
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(
                await socket.receive_json_from(timeout=5),
                {
                    "type": "program_channel_changed",
                    "content": {
                        "channel_id": self.program.pk,
                        "notify": True,
                        "message_id": response.json()["id"],
                    },
                },
            )
            await database_sync_to_async(set_notification_mode)(
                self.member, ProgramChannel, self.program.pk, "mentions"
            )
            post = database_sync_to_async(api.post)
            ordinary = await post(
                url, {"text": "Без упоминания"}, format="json", secure=True
            )
            self.assertEqual(ordinary.status_code, 201)
            self.assertFalse(
                (await socket.receive_json_from(timeout=5))["content"]["notify"]
            )
            mentioned = await post(
                url,
                {"text": "С упоминанием", "mentioned_user_ids": [self.member.pk]},
                format="json",
                secure=True,
            )
            self.assertEqual(mentioned.status_code, 201)
            self.assertTrue(
                (await socket.receive_json_from(timeout=5))["content"]["notify"]
            )
            await database_sync_to_async(self.profile.delete)()
            response = await database_sync_to_async(api.post)(
                url, {"text": "Следующая публикация"}, format="json", secure=True
            )
            self.assertEqual(response.status_code, 201)
            self.assertTrue(await socket.receive_nothing())
        finally:
            await socket.disconnect()
