from unittest.mock import Mock, patch
from uuid import uuid4

import requests
from channels.testing import HttpCommunicator, WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.admin import AdminSite
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.test import (
    AsyncClient,
    AsyncRequestFactory,
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.urls import reverse
from django.test import RequestFactory
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from chats.models import DirectChat, DirectChatMessage, FileToMessage, ProjectChatMessage
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.tests.test_project_reads import create_project_chat
from files.downloads import download_stored_file
from files.admin import UserFileAdmin
from files.models import UserFile
from files.views import FileView
from procollab.asgi import application
from projects.models import Collaborator

STORAGE = "https://storage.example.test/v1/account/media/"
TOKEN = "test-storage-token"


def upstream_file(status=200):
    upstream = Mock(status_code=status)
    upstream.headers = {"Content-Length": "6"}
    upstream.iter_content.return_value = iter([b"abc", b"def"])
    return upstream


@override_settings(ALLOWED_HOSTS=["testserver"], SELECTEL_SWIFT_URL=STORAGE)
class ChatAttachmentDownloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.author = users.create(**TEST_USER1, is_active=True)
        cls.member = users.create(
            **TEST_USER2, is_active=True, is_staff=True, is_superuser=True
        )
        cls.outsider = users.create(
            **TEST_USER3, is_active=True, is_staff=True, is_superuser=True
        )
        direct = DirectChat.get_chat(cls.author, cls.member)
        project = create_project_chat(cls.author, cls.member)
        cls.project = project
        cls.direct_message = DirectChatMessage.objects.create(
            chat=direct, author=cls.author, text="Личное сообщение"
        )
        cls.project_message = ProjectChatMessage.objects.create(
            chat=project, author=cls.author, text="Сообщение проекта"
        )
        cls.direct_attachment = cls.attach(cls.direct_message, "direct")
        cls.project_attachment = cls.attach(cls.project_message, "project")
        cls.other_chat = create_project_chat(cls.author, cls.member)

    @classmethod
    def attach(cls, message, label):
        file = UserFile.objects.create(
            link=STORAGE + label + ".pdf",
            user=cls.author,
            name="План проекта",
            extension="pdf",
            mime_type="application/pdf",
        )
        key = (
            "direct_message"
            if isinstance(message, DirectChatMessage)
            else "project_message"
        )
        return FileToMessage.objects.create(file=file, **{key: message})

    def setUp(self):
        self.api = APIClient()

    def authenticate_member(self):
        self.api.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.member)}"
        )

    @staticmethod
    def download_url(kind, message, attachment, chat_id=None):
        return reverse(
            "chats:" + kind + "-chat-attachment-download",
            args=[chat_id or message.chat_id, message.pk, attachment.download_id],
        )

    def test_history_and_file_list_return_the_same_protected_link(self):
        self.authenticate_member()
        for kind, message, attachment in (
            ("direct", self.direct_message, self.direct_attachment),
            ("project", self.project_message, self.project_attachment),
        ):
            with self.subTest(kind=kind):
                args = [message.chat_id]
                history = self.api.get(
                    reverse("chats:" + kind + "-chat-messages", args=args), secure=True
                ).json()
                files = self.api.get(
                    reverse("chats:" + kind + "-chat-files", args=args), secure=True
                ).json()
                link = self.download_url(kind, message, attachment)
                self.assertEqual(history["results"][0]["files"][0]["link"], link)
                self.assertEqual(files[0]["link"], link)
                self.assertEqual(files[0]["name"], "План проекта")
                self.assertNotIn(STORAGE, str(history) + str(files))

    def test_published_attachment_is_retained_until_message_is_deleted(self):
        self.api.force_authenticate(self.author)
        for attachment, message in (
            (self.direct_attachment, self.direct_message),
            (self.project_attachment, self.project_message),
        ):
            with self.subTest(message=message):
                query = {"QUERY_STRING": "link=" + attachment.file_id}
                with patch.object(FileView.cdn.storage, "delete") as storage_delete:
                    response = self.api.delete("/files/", secure=True, **query)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json()["code"], "chat_attachment_in_use")
                    storage_delete.assert_not_called()
                    with self.assertRaises(ProtectedError), transaction.atomic():
                        UserFile.objects.filter(pk=attachment.file_id).delete()
                    self.assertTrue(
                        FileToMessage.objects.filter(pk=attachment.pk).exists()
                    )

                    message.is_deleted = True
                    message.save(update_fields=["is_deleted"])
                    self.assertEqual(
                        self.api.delete("/files/", secure=True, **query).status_code, 204
                    )
                    storage_delete.assert_called_once_with(attachment.file_id)
                self.assertFalse(UserFile.objects.filter(pk=attachment.file_id).exists())

    def test_admin_bulk_delete_checks_every_file_before_contacting_storage(self):
        unused = UserFile.objects.create(link=STORAGE + "unused.pdf", user=self.author)
        files = UserFile.objects.filter(
            pk__in=[unused.pk, self.project_attachment.file_id]
        )
        request = RequestFactory().post("/admin/files/userfile/")
        request.user = self.member
        file_admin = UserFileAdmin(UserFile, AdminSite())
        with patch.object(file_admin.cdn, "delete") as storage_delete:
            with self.assertRaises(PermissionDenied):
                file_admin.delete_queryset(request, files)
            storage_delete.assert_not_called()
        self.assertEqual(files.count(), 2)

    def test_attachment_link_admin_is_read_only(self):
        self.client.force_login(self.member)
        route = "admin:chats_filetomessage"
        self.assertEqual(
            self.client.get(reverse(route + "_changelist"), secure=True).status_code, 200
        )
        url = reverse(route + "_delete", args=[self.project_attachment.pk])
        self.assertEqual(
            self.client.post(url, {"post": "yes"}, secure=True).status_code, 403
        )
        self.assertTrue(
            FileToMessage.objects.filter(pk=self.project_attachment.pk).exists()
        )

    @patch("files.downloads.SelectelSwiftStorage._get_auth_token", return_value=TOKEN)
    @patch("files.downloads.requests.get")
    def test_members_can_download_through_api_and_admin(self, storage_get, _token):
        self.authenticate_member()
        self.client.force_login(self.member)
        admin_url = reverse(
            "admin:chats_projectchat_message_search_download",
            args=[
                self.project.pk,
                self.project_message.pk,
                self.project_attachment.download_id,
            ],
        )
        search = self.client.get(
            reverse("admin:chats_projectchat_message_search", args=[self.project.pk]),
            secure=True,
        )
        self.assertContains(search, admin_url)
        for client, url, expected_file in (
            (
                self.api,
                self.download_url("direct", self.direct_message, self.direct_attachment),
                self.direct_attachment.file_id,
            ),
            (
                self.api,
                self.download_url(
                    "project", self.project_message, self.project_attachment
                ),
                self.project_attachment.file_id,
            ),
            (self.client, admin_url, self.project_attachment.file_id),
        ):
            with self.subTest(url=url):
                upstream = upstream_file()
                storage_get.return_value = upstream
                response = client.get(url, secure=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/octet-stream")
                self.assertIn("filename*=utf-8''", response["Content-Disposition"])
                self.assertIn("no-store", response["Cache-Control"])
                self.assertEqual(response["Content-Length"], "6")
                self.assertEqual(b"".join(response.streaming_content), b"abcdef")
                upstream.close.assert_called_once()
                storage_get.assert_called_with(
                    expected_file,
                    headers={"X-Auth-Token": TOKEN, "Accept-Encoding": "identity"},
                    stream=True,
                    timeout=(5, 15),
                    allow_redirects=False,
                )

        upstream = upstream_file()
        storage_get.return_value = upstream
        response = self.api.head(
            self.download_url("direct", self.direct_message, self.direct_attachment),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Length"], "6")
        self.assertEqual(response.content, b"")
        upstream.iter_content.assert_not_called()
        upstream.close.assert_called_once()

    @patch("files.downloads.SelectelSwiftStorage._get_auth_token")
    @patch("files.downloads.requests.get")
    def test_access_and_message_checks_run_before_storage(self, storage_get, token):
        url = self.download_url("project", self.project_message, self.project_attachment)
        self.assertEqual(self.api.get(url, secure=True).status_code, 401)
        self.api.force_authenticate(self.outsider)
        self.assertEqual(self.api.get(url, secure=True).status_code, 404)
        direct_url = self.download_url(
            "direct", self.direct_message, self.direct_attachment
        )
        self.assertEqual(self.api.get(direct_url, secure=True).status_code, 404)
        self.client.force_login(self.outsider)
        admin_url = reverse(
            "admin:chats_projectchat_message_search_download",
            args=[
                self.project.pk,
                self.project_message.pk,
                self.project_attachment.download_id,
            ],
        )
        self.assertEqual(self.client.get(admin_url, secure=True).status_code, 404)

        self.api.force_authenticate(self.member)
        wrong_chat = self.download_url(
            "project",
            self.project_message,
            self.project_attachment,
            chat_id=self.other_chat.pk,
        )
        wrong_file = self.download_url(
            "project", self.project_message, self.direct_attachment
        )
        for unavailable in (wrong_chat, wrong_file):
            self.assertEqual(self.api.get(unavailable, secure=True).status_code, 404)
        Collaborator.objects.filter(
            project=self.project.project, user=self.member
        ).delete()
        self.assertEqual(self.api.get(url, secure=True).status_code, 404)
        self.api.force_authenticate(self.author)
        self.project_message.is_deleted = True
        self.project_message.save(update_fields=["is_deleted"])
        self.assertEqual(self.api.get(url, secure=True).status_code, 404)
        files_url = reverse("chats:project-chat-files", args=[self.project.pk])
        self.assertEqual(self.api.get(files_url, secure=True).json(), [])
        token.assert_not_called()
        storage_get.assert_not_called()

    @patch("files.downloads.SelectelSwiftStorage._get_auth_token", return_value=TOKEN)
    @patch("files.downloads.requests.get")
    def test_storage_errors_do_not_redirect_the_client(self, storage_get, _token):
        self.authenticate_member()
        url = self.download_url("direct", self.direct_message, self.direct_attachment)
        for upstream_status, expected in ((404, 404), (302, 502), (503, 502)):
            with self.subTest(upstream_status=upstream_status):
                upstream = upstream_file(upstream_status)
                upstream.headers["Location"] = "https://storage.example.test/redirect"
                storage_get.return_value = upstream
                response = self.api.get(url, secure=True)
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("Location", response)
                self.assertIn("no-store", response["Cache-Control"])
                upstream.close.assert_called_once()
        storage_get.side_effect = requests.Timeout
        self.assertEqual(self.api.get(url, secure=True).status_code, 502)

    @patch("files.downloads.SelectelSwiftStorage._get_auth_token")
    @patch("files.downloads.requests.get")
    def test_download_uses_only_configured_storage(self, storage_get, token):
        self.authenticate_member()
        file = UserFile.objects.create(
            link="https://other.example.test/files/file.pdf",
            user=self.author,
        )
        attachment = FileToMessage.objects.create(
            file=file, direct_message=self.direct_message
        )
        url = self.download_url("direct", self.direct_message, attachment)
        self.assertEqual(self.api.get(url, secure=True).status_code, 404)
        token.assert_not_called()
        storage_get.assert_not_called()


@override_settings(SELECTEL_SWIFT_URL=STORAGE)
class AsyncAttachmentDownloadTests(SimpleTestCase):
    @patch("files.downloads.SelectelSwiftStorage._get_auth_token", return_value=TOKEN)
    @patch("files.downloads.requests.get")
    async def test_asgi_consumes_the_upstream_one_chunk_at_a_time(
        self, storage_get, _token
    ):
        upstream = upstream_file()
        storage_get.return_value = upstream
        file = UserFile(link=STORAGE + "object", name="План", extension="pdf")
        response = download_stored_file(AsyncRequestFactory().get("/"), file)
        self.assertTrue(response.is_async)
        self.assertEqual(
            [chunk async for chunk in response.streaming_content], [b"abc", b"def"]
        )
        response.close()
        upstream.close.assert_called_once()


@override_settings(ALLOWED_HOSTS=["testserver"], SELECTEL_SWIFT_URL=STORAGE.rstrip("/"))
class ChatAttachmentRoundTripTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        self.author = users.create(**TEST_USER1, is_active=True)
        self.reader = users.create(**TEST_USER2, is_active=True)
        self.chat = create_project_chat(self.author, self.reader)

    async def send(self, token, payload):
        socket = WebsocketCommunicator(
            application, "/ws/chat/", subprotocols=["Bearer", token]
        )
        self.assertEqual(await socket.connect(timeout=5), (True, "Bearer"))
        try:
            await socket.send_json_to(payload)
            event = await socket.receive_json_from(timeout=5)
            self.assertEqual(event["type"], "new_message")
            return event["content"]
        finally:
            await socket.disconnect()

    async def test_upload_reconnect_and_download_keep_original_file(self):
        author_token = str(AccessToken.for_user(self.author))
        reader_token = str(AccessToken.for_user(self.reader))
        reader = AsyncClient(authorization=f"Bearer {reader_token}")
        history_url = reverse("chats:project-chat-messages", args=[self.chat.pk])
        history = await reader.get(history_url, secure=True)
        self.assertEqual(history.status_code, 200)
        cursor = history.json()["sync_cursor"]
        original = bytes(range(256)) * 300
        uploaded = {}

        def store(url, *, data, **kwargs):
            self.assertTrue(url.startswith(STORAGE))
            self.assertEqual(kwargs["headers"]["X-Auth-Token"], TOKEN)
            uploaded[url] = data.read()
            return Mock(status_code=201)

        def fetch(url, **kwargs):
            self.assertEqual(kwargs["headers"]["X-Auth-Token"], TOKEN)
            content = uploaded[url]
            upstream = Mock(
                status_code=200, headers={"Content-Length": str(len(content))}
            )
            view = memoryview(content)
            upstream.iter_content.side_effect = lambda chunk_size: (
                bytes(view[offset:][:chunk_size])
                for offset in range(0, len(content), chunk_size)
            )
            return upstream

        with (
            patch(
                "files.service.requests.post",
                return_value=Mock(status_code=201, headers={"x-subject-token": TOKEN}),
            ),
            patch("files.service.requests.put", side_effect=store) as upload,
            patch("files.downloads.requests.get", side_effect=fetch) as download,
        ):
            sender = AsyncClient(authorization=f"Bearer {author_token}")
            response = await sender.post(
                "/files/?preserve_original=true",
                {"file": SimpleUploadedFile("План.bin", original)},
                secure=True,
            )
            self.assertEqual(response.status_code, 201)
            storage_url = response.json()["url"]
            payload = {
                "type": "new_message",
                "content": {
                    "chat_type": "project",
                    "chat_id": self.chat.pk,
                    "client_message_id": str(uuid4()),
                    "file_urls": [storage_url],
                },
            }
            first = await self.send(author_token, payload)
            replay = await self.send(author_token, payload)
            self.assertFalse(first["is_replay"])
            self.assertTrue(replay["is_replay"])
            self.assertEqual(first["message"], replay["message"])

            changes_url = reverse(
                "chats:project-chat-message-changes", args=[self.chat.pk]
            )
            changes = await reader.get(changes_url, {"after": cursor}, secure=True)
            self.assertEqual(changes.status_code, 200)
            (change,) = changes.json()["results"]
            self.assertEqual(change["message_id"], first["message"]["id"])
            link = change["message"]["files"][0]["link"]
            self.assertTrue(link.startswith("/chats/"))
            download_request = HttpCommunicator(
                application,
                "GET",
                link,
                headers=[
                    (b"host", b"testserver"),
                    (b"authorization", f"Bearer {reader_token}".encode()),
                ],
            )
            download_request.scope["scheme"] = "https"
            await download_request.send_input({"type": "http.request", "body": b""})
            result = await download_request.receive_output(timeout=5)
            self.assertEqual(result["type"], "http.response.start")
            self.assertEqual(result["status"], 200)
            headers = {name.lower(): value for name, value in result["headers"]}
            chunks = []
            while True:
                chunk = await download_request.receive_output(timeout=5)
                self.assertEqual(chunk["type"], "http.response.body")
                chunks.append(chunk.get("body", b""))
                if not chunk.get("more_body"):
                    break
            await download_request.wait(timeout=5)
            self.assertGreater(sum(bool(chunk) for chunk in chunks), 1)
            self.assertEqual(b"".join(chunks), original)
            self.assertEqual(headers[b"content-length"], str(len(original)).encode())
            self.assertIn(b"filename*=utf-8''", headers[b"content-disposition"])
            self.assertIn(b"no-store", headers[b"cache-control"])
            upload.assert_called_once()
            download.assert_called_once()
        self.assertEqual(await self.chat.messages.acount(), 1)
